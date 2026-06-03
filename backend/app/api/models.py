"""Pydantic request/response models for API endpoints."""

from pydantic import BaseModel, Field, field_validator
import re

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
ALLOWED_ROLES = {"user", "assistant", "system"}

# Upper bound on how many messages a single request may carry. Chat history is
# trimmed to a handful of turns before inference anyway, so this only exists to
# bound per-request CPU/memory (sanitization runs over every element).
MAX_MESSAGES_PER_REQUEST = 200


class _ConversationIdMixin(BaseModel):
    conversation_id: str

    @field_validator("conversation_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        if not v or not UUID_RE.match(v):
            raise ValueError("Invalid conversation_id format")
        return v


class ChatRequest(BaseModel):
    messages: list = Field(..., min_length=1, max_length=MAX_MESSAGES_PER_REQUEST)
    search: bool = False
    chat_upload_local_path: str | None = None


class DeleteAttachmentRequest(BaseModel):
    path: str = Field(..., min_length=1)


class DeepResearchRequest(BaseModel):
    messages: list = Field(..., min_length=1, max_length=MAX_MESSAGES_PER_REQUEST)
    chat_upload_local_path: str | None = None


class CreateConversationRequest(BaseModel):
    messages: list = Field(..., min_length=1, max_length=MAX_MESSAGES_PER_REQUEST)


class AddMessageRequest(_ConversationIdMixin):
    role: str
    content: str | list = ""
    isDeepResearch: bool = False
    progress: str | None = None
    attachmentPath: str | None = None
    attachmentName: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(ALLOWED_ROLES))}")
        return v


class UpdateTitleRequest(_ConversationIdMixin):
    new_title: str = Field(..., min_length=1, max_length=200)


class ConversationIdRequest(_ConversationIdMixin):
    pass
