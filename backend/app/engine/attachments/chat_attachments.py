import base64
import io
import os
import pandas as pd
import pypdfium2 as pdfium
from app.engine.attachments.retrieval import keyword_search

# Keep in sync with frontend `CHAT_ATTACHMENT_EXTENSIONS` in chatAttachmentPicker.ts
ALLOWED_EXTENSIONS = [
    "png",
    "jpg",
    "jpeg",
    "pdf",
    "xlsx",
    "csv",
    "parquet",
    "json"
]

TABLE_EXTENSIONS = {"csv", "xlsx", "parquet", "json"}

# Single-slot cache so a file is only read/parsed from disk once while it stays
# selected.  For images/PDFs the full message content list is cached.  For
# tabular files the loaded DataFrame is cached (BM25 search still runs per
# message since the query changes).
_cache_path: str | None = None
_cache_content: list | None = None      # images/PDF pages (reusable as-is)
_cache_dataframe: pd.DataFrame | None = None  # table data (needs per-query search)


def _invalidate_cache():
    global _cache_path, _cache_content, _cache_dataframe
    _cache_path = None
    _cache_content = None
    _cache_dataframe = None


MAX_PDF_PAGES = 50

# Render scale relative to PDF's native 72 DPI; matches the previous 150 DPI output.
_PDF_RENDER_SCALE = 150 / 72


def parse_pdf(path):

  doc = pdfium.PdfDocument(path)

  messages_content = []

  try:
    for idx in range(min(len(doc), MAX_PDF_PAGES)):
      page = doc[idx]
      bitmap = page.render(scale=_PDF_RENDER_SCALE)
      pil_image = bitmap.to_pil()

      buffer = io.BytesIO()
      pil_image.convert("RGB").save(buffer, format="JPEG")
      b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

      bitmap.close()
      page.close()

      messages_content.append({
          "type": "image_url",
          "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
      })
  finally:
    doc.close()

  return messages_content


def parse_image(path: str) -> list:

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    ext = path.rsplit(".", 1)[-1].lower()
    mime_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    mime_type = mime_types.get(ext, "image/jpeg")

    return [{
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{b64}"}
    }]


def _load_dataframe(path, ext):
    if ext == 'csv':
        return pd.read_csv(path)
    elif ext == 'xlsx':
        return pd.read_excel(path)
    elif ext == 'parquet':
        return pd.read_parquet(path)
    elif ext == 'json':
        return pd.read_json(path)


def _search_table(df, user_prompt):
    relevant_documents = keyword_search(df, user_prompt)
    text = str(relevant_documents)[:10000]
    return [{"type": "text", "text": f"[Attachment — table search results]\n{text}"}]


def parse_file(path, user_prompt):
    global _cache_path, _cache_content, _cache_dataframe

    ext = os.path.splitext(path)[1].lstrip(".").lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid extension: {ext}")

    # If the path changed, drop old cache
    if _cache_path != path:
        _invalidate_cache()
        _cache_path = path  # intentionally set before populating values below

    if ext in ['png', 'jpg', 'jpeg']:
        if _cache_content is None:
            _cache_content = parse_image(path)
        return _cache_content

    elif ext == 'pdf':
        if _cache_content is None:
            _cache_content = parse_pdf(path)
        return _cache_content

    elif ext in TABLE_EXTENSIONS:
        if _cache_dataframe is None:
            _cache_dataframe = _load_dataframe(path, ext)
        return _search_table(_cache_dataframe, user_prompt)


def add_file_to_message(message, path):
    """Return a copy of ``message`` with ``path``'s parsed content inlined.

    The original text is preserved as the first content part so the attachment
    stays anchored to the message the user attached it to.
    """
    content = message.get('content', '')
    text = content if isinstance(content, str) else ''

    messages_content = parse_file(path, text)

    return {
        'role': message.get('role', 'user'),
        'content': [{'type': 'text', 'text': text}] + messages_content,
    }


def add_attachment_to_messages(messages, path):

    last_user_message = [m for m in messages if m['role'] == 'user'][-1]

    inlined = add_file_to_message(last_user_message, path)

    return messages[:-1] + [inlined]