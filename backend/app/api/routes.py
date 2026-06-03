import os
import logging
import re
import hmac
import hashlib
import tempfile
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Header
from fastapi.responses import PlainTextResponse, StreamingResponse, JSONResponse
from app.engine.llm.inference import stream_llm_response
from app.api.models import (
    ChatRequest,
    CreateConversationRequest,
    AddMessageRequest,
    UpdateTitleRequest,
    ConversationIdRequest,
    DeleteAttachmentRequest,
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.sanitization import (
    sanitize_messages,
    sanitize_user_input,
)
from app.engine.attachments.chat_attachments import (
    ALLOWED_EXTENSIONS,
    add_attachment_to_messages,
    add_file_to_message,
)
from app.core.startup_state import get_startup_snapshot

from app.api.conversations import (
    create_new_conversation,
    add_message_to_conversation,
    update_conversation_title,
    delete_conversation,
    get_all_conversations,
    get_conversation_by_id,
)

logger = logging.getLogger(__name__)

# Shared rate limiter. Defined at import time so the decorators below wrap the
# real endpoints in the standard slowapi order (`@router.post` on top,
# `@limiter.limit` underneath). main.py wires this same instance into
# `app.state.limiter`.
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_TITLE_LENGTH = 200
ALLOWED_ROLES = {"user", "assistant", "system"}

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

_MIME_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "pdf":     [(0, b"%PDF")],
    "png":     [(0, b"\x89PNG\r\n\x1a\n")],
    "jpg":     [(0, b"\xff\xd8\xff")],
    "jpeg":    [(0, b"\xff\xd8\xff")],
    "xlsx":    [(0, b"PK\x03\x04")],
    "parquet": [(0, b"PAR1")],
}


def _validate_mime(header: bytes, extension: str) -> bool:
    """Return True when magic bytes are consistent with the claimed extension.

    Extensions without a known signature (csv, json) are accepted by default.
    """
    sigs = _MIME_SIGNATURES.get(extension)
    if sigs is None:
        return True
    for offset, magic in sigs:
        if header[offset:offset + len(magic)] == magic:
            return True
    return False


def _cleanup_temp_file(path: str | None) -> None:
    """Best-effort removal of a temp attachment (e.g. when user removes or replaces it)."""
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _validate_temp_attachment_path(path: str, *, must_exist: bool) -> str:
    """Ensure path is inside the system temp directory and contains no traversal."""
    resolved = Path(path).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not str(resolved).startswith(str(tmp_root) + os.sep) and resolved != tmp_root:
        raise HTTPException(status_code=400, detail="Invalid attachment path")
    if must_exist and not resolved.is_file():
        raise HTTPException(status_code=400, detail="Attachment file not found")
    return str(resolved)


def _validate_upload_path(path: str) -> str:
    return _validate_temp_attachment_path(path, must_exist=True)


def _attach_message_files(messages: list) -> list:
    """Inline per-message attachments so a file stays anchored to the message
    the user attached it to and remains available on every follow-up turn.

    A file that stays selected in the composer is recorded on each message the
    user sends while it is attached, so the same path appears repeatedly. We
    inline it only once — on its first occurrence — to keep the file in its
    natural position in the conversation and avoid feeding the model duplicate
    copies of the same image.

    The ``attachmentPath`` key is always stripped from the outgoing message. If
    the referenced temp file is missing or outside the temp dir, the attachment
    is silently dropped (e.g. it was cleared, or the app restarted) rather than
    failing the whole request.
    """
    result = []
    seen_paths: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            result.append(message)
            continue

        path = message.get("attachmentPath")
        stripped = {k: v for k, v in message.items() if k != "attachmentPath"}

        if (
            path
            and path not in seen_paths
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ):
            seen_paths.add(path)
            try:
                safe_path = _validate_temp_attachment_path(path, must_exist=True)
                result.append(add_file_to_message(stripped, safe_path))
                continue
            except HTTPException:
                logger.warning("Skipping unavailable attachment for message")
            except Exception as e:
                logger.error(f"Failed to attach message file: {e}", exc_info=True)

        result.append(stripped)

    return result


@router.get("/", include_in_schema=False)
def root():
    return {
        "message": "Quantscript Private Chat API",
        "description": "Quantscript Private Chat API",
    }


@router.get("/healthz", include_in_schema=False)
def healthz(): return PlainTextResponse("ok")


@router.get("/startup_status", include_in_schema=False)
def startup_status():
    """Poll while the UI blocks; mirrors backend startup phases."""
    return JSONResponse(get_startup_snapshot())


@router.get("/startup_status_probe", include_in_schema=False)
def startup_status_probe(x_startup_nonce: str | None = Header(default=None)):
    """Return a nonce-bound proof so the shell can verify backend authenticity."""
    token = os.environ.get("QUANTSCRIPT_SIDECAR_TOKEN")
    if not token or not x_startup_nonce:
        raise HTTPException(status_code=400, detail="Missing startup probe context")
    proof = hmac.new(
        token.encode("utf-8"),
        x_startup_nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return PlainTextResponse(proof)


@router.post("/stream_text_response")
@limiter.limit("30/minute")
async def stream_text_response(request: Request, body: ChatRequest):
    messages = body.messages
    search = body.search
    chat_upload_local_path = body.chat_upload_local_path

    # Inline per-message attachments so files stay with their message across
    # follow-up turns (the model keeps access for the whole conversation).
    messages = _attach_message_files(messages)

    # Back-compat: a request-level attachment is pinned to the latest message.
    if chat_upload_local_path:
        chat_upload_local_path = _validate_upload_path(chat_upload_local_path)
        messages = add_attachment_to_messages(messages, chat_upload_local_path)
    
    # Sanitize user input
    messages = sanitize_messages(messages)

    def response_generator():
        try:
            response = stream_llm_response(messages,search=search)
            for chunk in response:
                yield chunk
        except Exception as e:
            logger.error(f"Error in stream_text_response generator: {e}", exc_info=True)
            yield f"\n\n[Error: An unexpected error occurred]"

    return StreamingResponse(response_generator(), media_type="text/plain")


@router.post("/delete_chat_attachment")
@limiter.limit("30/minute")
async def delete_chat_attachment(request: Request, body: DeleteAttachmentRequest):
    """Remove a temp attachment when the user clears or replaces it in the UI."""
    path = _validate_temp_attachment_path(body.path, must_exist=False)
    _cleanup_temp_file(path)
    return {"status": "success"}


@router.post("/create_conversation")
@limiter.limit("60/minute")
async def create_conversation(request: Request, body: CreateConversationRequest):
    """Create a new conversation."""
    messages = sanitize_messages(body.messages)
    conversation_id = create_new_conversation(messages)
    message = messages[0]
    message['conversation_id'] = conversation_id
    try:
        add_message_to_conversation(message)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "message": "Conversation created successfully", "conversation_id": conversation_id}


@router.post("/add_message_to_conversation")
@limiter.limit("120/minute")
async def add_message(request: Request, body: AddMessageRequest):
    """Add a message to a conversation."""
    message = body.model_dump()

    content = message.get("content", "")
    if isinstance(content, str):
        message["content"] = sanitize_user_input(content)
    elif isinstance(content, list):
        message["content"] = sanitize_messages([{"role": message["role"], "content": content}])[0]["content"]
    try:
        add_message_to_conversation(message)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "message": "Message added to conversation successfully"}


@router.post("/update_conversation_title")
@limiter.limit("60/minute")
async def update_title(request: Request, body: UpdateTitleRequest):
    """Update conversation title."""
    new_title = sanitize_user_input(body.new_title, max_length=MAX_TITLE_LENGTH)
    if not new_title:
        raise HTTPException(status_code=400, detail="new_title is required")
    try:
        update_conversation_title(body.conversation_id, new_title)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "message": "Conversation title updated successfully"}


@router.post("/delete_conversation")
@limiter.limit("60/minute")
async def delete(request: Request, body: ConversationIdRequest):
    """Delete a conversation."""
    delete_conversation(body.conversation_id)
    return {"status": "success", "message": "Conversation deleted successfully"}


@router.post("/get_all_conversations")
@limiter.limit("60/minute")
async def all_conversations(request: Request):
    """Get all conversations."""
    conversations = get_all_conversations()
    return {"status": "success", "conversations": conversations}


@router.post("/get_conversation_by_id")
@limiter.limit("60/minute")
async def conversation_by_id(request: Request, body: ConversationIdRequest):
    """Get a conversation by ID."""
    try:
        conversation = get_conversation_by_id(body.conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "conversation": conversation}


@router.post("/upload_chat_attachment")
@limiter.limit("10/minute")
async def upload_chat_attachment(request: Request, file: UploadFile = File(...)):
    """Accept a file upload for chat attachments and return a temp path."""
    suffix = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '.{suffix}' is not allowed")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
            tmp_path = tmp.name
            total = 0
            first_chunk = True
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)} MB)")
                if first_chunk:
                    if not _validate_mime(chunk, suffix):
                        raise HTTPException(status_code=400, detail="File content does not match its extension")
                    first_chunk = False
                tmp.write(chunk)
            return JSONResponse({"path": tmp.name})
    except HTTPException:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise