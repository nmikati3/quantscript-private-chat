import os
import gc
import re
from app.engine.llm.prompts import create_title_from_messages_prompt, write_web_search_query_prompt
from pydantic import BaseModel
import logging
from llama_cpp import Llama
from app.engine.llm.prompts import compute_web_search_system_prompt, write_web_search_query_prompt, text_response_prompt
from app.engine.llm.web_search import web_search_and_fetch_articles
import json
from llama_cpp.llama_chat_format import Llava16ChatHandler
from app.engine.llm.model_download import download_model_files, download_mmproj
from app.engine.llm.model_tiers import resolve_model_config
from app.core.startup_state import is_ready, set_phase_progress

logger = logging.getLogger(__name__)

MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
CHAT_HISTORY_MAX_MESSAGES = int(os.environ.get("CHAT_HISTORY_MAX_MESSAGES", "5"))

# Pick the model variant/quant/context that fits this machine's unified memory
# (env vars still override every field — see model_tiers.resolve_model_config).
_MODEL_CONFIG = resolve_model_config()
LLAMA_REPO_ID = _MODEL_CONFIG["repo_id"]
LLAMA_FILENAME = _MODEL_CONFIG["filename"]
N_CTX = _MODEL_CONFIG["n_ctx"]
LLAMA_MMPROJ_FILENAME = _MODEL_CONFIG["mmproj_filename"]

# Chat-template modes. The model speaks a different template per mode, and the
# template is fixed at construction time, so changing mode means rebuilding the
# Llama object (see `initialize_llama`).
MODE_TEXT = "text"            # plain chat -> the model's native Gemma template
MODE_VISION = "vision"        # a file is attached -> multimodal LLaVA handler
MODE_DEEP_RESEARCH = "deep_research"  # deterministic JSON workflow -> Gemma template

MMPROJ_PATH: str | None = None
CHAT_HANDLER = None
CLIENT_LLAMA = None
# The mode the currently-loaded model was built with, so we can skip an
# expensive reload when the next request needs the same template.
_CURRENT_MODE: str | None = None


def _ensure_mmproj_path(report_progress: bool) -> str:
    global MMPROJ_PATH
    if MMPROJ_PATH is not None:
        return MMPROJ_PATH
    if not LLAMA_REPO_ID or not LLAMA_MMPROJ_FILENAME:
        raise RuntimeError("LLAMA_REPO_ID and LLAMA_MMPROJ_FILENAME must be set")
    MMPROJ_PATH = download_mmproj(
        "llm",
        LLAMA_REPO_ID,
        LLAMA_MMPROJ_FILENAME,
        report_progress=report_progress,
    )
    return MMPROJ_PATH


def _get_chat_handler(mode: str) -> dict:
    """Return the `Llama` chat-template kwargs to use for the given mode.

    This is the single place that decides how the model is prompted, so it
    speaks the template it was actually trained on:
      - file attached -> ``Llava16ChatHandler`` (multimodal / vision)
      - otherwise     -> ``chat_format="gemma"`` (the model's native template)

    Deep research uses the native Gemma template too: it is a deterministic,
    structured-JSON workflow that drives web search from orchestration code, so
    it no longer needs the ``chatml-function-calling`` template (which prompted
    Gemma off-distribution and silently dropped tool-result messages).
    """
    global CHAT_HANDLER

    if mode == MODE_VISION:
        if CHAT_HANDLER is None:
            report = not is_ready()
            CHAT_HANDLER = Llava16ChatHandler(
                clip_model_path=_ensure_mmproj_path(report_progress=report),
                verbose=False,
            )
        return {"chat_handler": CHAT_HANDLER}

    # Plain text chat: use Gemma's own chat template (correct turn markers and
    # stop tokens) instead of the vision handler's generic concatenation.
    return {"chat_format": "gemma"}


def _messages_have_attachment(messages) -> bool:
    """True when any message carries inlined file content.

    Attachment processing turns a message's ``content`` into a list of parts
    (image/PDF pages or table-search text); plain text turns keep a string. Only
    the list form needs the multimodal chat handler.
    """
    return any(
        isinstance(m, dict) and isinstance(m.get("content"), list)
        for m in messages
    )


def _resolve_model_mode(deep_research: bool, has_attachment: bool) -> str:
    if deep_research:
        return MODE_DEEP_RESEARCH
    if has_attachment:
        return MODE_VISION
    return MODE_TEXT


def _close_resource(resource, label: str) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as e:
        logger.warning("Failed to close %s: %s", label, e)


def _unload_llama() -> None:
    """Release the loaded model and vision handler before swapping variants."""
    global CLIENT_LLAMA, CHAT_HANDLER, _CURRENT_MODE

    _close_resource(CLIENT_LLAMA, "LLM client")
    CLIENT_LLAMA = None

    _close_resource(CHAT_HANDLER, "chat handler")
    CHAT_HANDLER = None

    _CURRENT_MODE = None

    gc.collect()


def initialize_llama(deep_research=False, has_attachment=False):
    """Ensure the model is loaded with the right chat template for the request.

    The chat template is fixed when the ``Llama`` object is built, so switching
    between text, vision and deep-research modes requires rebuilding it. We track
    the active mode and only reload when it actually changes.
    """
    global CLIENT_LLAMA, MMPROJ_PATH, _CURRENT_MODE

    if not LLAMA_REPO_ID or not LLAMA_FILENAME:
        raise RuntimeError("LLAMA_REPO_ID and LLAMA_FILENAME must be set")

    mode = _resolve_model_mode(deep_research, has_attachment)

    # Already loaded with the right template — reuse it (avoids reloading the
    # whole model on every message).
    if CLIENT_LLAMA is not None and _CURRENT_MODE == mode:
        return CLIENT_LLAMA

    _unload_llama()

    report_progress = not is_ready()
    phase_id = "llm"

    # Only the vision handler needs the multimodal projector.
    needs_vision = mode == MODE_VISION
    main_path, mmproj_path = download_model_files(
        phase_id,
        LLAMA_REPO_ID,
        main_filename=LLAMA_FILENAME,
        mmproj_filename=LLAMA_MMPROJ_FILENAME if needs_vision else None,
        report_progress=report_progress,
    )
    if mmproj_path:
        MMPROJ_PATH = mmproj_path

    if report_progress:
        set_phase_progress(phase_id, percent=99, detail="Loading model into memory…")

    CLIENT_LLAMA = Llama(
        model_path=main_path,
        n_ctx=N_CTX,
        n_gpu_layers=-1,
        flash_attn=True,
        verbose=False,
        **_get_chat_handler(mode),
    )
    _CURRENT_MODE = mode

    return CLIENT_LLAMA


def trim_chat_messages(messages: list, max_messages: int | None = None) -> list:
    """Keep only the most recent non-system messages to avoid context-window hangs. This is especially important when running locally as a context too large will significantly slow down the responses."""
    limit = max_messages if max_messages is not None else CHAT_HISTORY_MAX_MESSAGES
    if limit <= 0 or not messages:
        return messages

    non_system = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]

    if len(non_system) <= limit:
        return messages

    trimmed = non_system[-limit:]
    return  trimmed


def _apply_system_prompt(messages: list, system_prompt: str) -> list:
    """Attach the system prompt in a form the active chat template will honor.

    Gemma's template ignores ``system`` role messages, so in text mode the
    instructions are merged into the most recent user turn instead (otherwise
    the system prompt — including web-search article context — would be silently
    dropped). Vision and deep-research templates keep a real system message,
    placed just before the final user turn as before.
    """
    if not system_prompt:
        return messages

    if _CURRENT_MODE == MODE_TEXT:
        merged = list(messages)
        for i in range(len(merged) - 1, -1, -1):
            m = merged[i]
            if (
                isinstance(m, dict)
                and m.get("role") == "user"
                and isinstance(m.get("content"), str)
            ):
                merged[i] = {**m, "content": f"{system_prompt}\n\n{m['content']}"}
                return merged
        # No user turn to merge into; fall back to a leading system message.
        return [{"role": "system", "content": system_prompt}] + merged

    return messages[:-1] + [{"role": "system", "content": system_prompt}] + messages[-1:]


def write_web_search_query(messages):

    class WriteWebSearchQuery(BaseModel):
        query: str

    messages = trim_chat_messages(messages)

    # Only role + string content for the chat API (drop attachmentPath, etc.)
    slim = []
    for m in messages:
        if not isinstance(m, dict) or "role" not in m:
            continue
        c = m.get("content", "")
        if not isinstance(c, str):
            c = ""
        slim.append({"role": m["role"], "content": c})

    if not slim:
        return "No messages found."

    messages = _apply_system_prompt(slim, write_web_search_query_prompt)

    response = get_structured_llm_response(WriteWebSearchQuery, messages)

    return response.query


def web_search_system_prompt(messages):

    query = write_web_search_query(messages)

    articles = web_search_and_fetch_articles(query, n=5)

    system_prompt = compute_web_search_system_prompt(articles)

    return system_prompt


# Sampling temperatures tried in order. The model occasionally samples a stop
# token before emitting any text (an "empty response"); a near-greedy retry
# makes that far less likely than the default high-temperature pass.
EMPTY_RESPONSE_RETRY_TEMPERATURES = (1.0, 0.3)

EMPTY_RESPONSE_FALLBACK = (
  "I wasn't able to generate a response to that. Could you try rephrasing your question?"
)


def _stream_completion_once(messages, temperature):
  """Yield non-empty content deltas from a single streamed completion."""
  response = CLIENT_LLAMA.create_chat_completion(
    messages=messages,
    stream=True,
    max_tokens=MAX_TOKENS,
    temperature=temperature,
    top_p=0.95,
    top_k=64,
  )
  for chunk in response:
    choices = chunk.get("choices")
    if not choices:
      continue
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    if content:
      yield content


def stream_llm_response(messages,search=False):

  messages = trim_chat_messages(messages)
  messages = [m for m in messages if m["role"] != "system"]

  # Load the model with the right chat template for this request: the vision
  # handler when a file is attached, otherwise Gemma's native template. This
  # reloads the model only when the mode actually changes.
  has_attachment = _messages_have_attachment(messages)
  initialize_llama(deep_research=False, has_attachment=has_attachment)

  if search:
    system_prompt = web_search_system_prompt(messages)
  else:
    system_prompt = text_response_prompt

  messages = _apply_system_prompt(messages, system_prompt)

  for attempt, temperature in enumerate(EMPTY_RESPONSE_RETRY_TEMPERATURES):
    produced_any = False
    # Hold leading whitespace so an all-whitespace reply can be retried as
    # "empty" instead of being streamed out as a blank-looking response.
    pending_whitespace = ""
    try:
      for content in _stream_completion_once(messages, temperature=temperature):
        if not produced_any and not content.strip():
          pending_whitespace += content
          continue
        if pending_whitespace:
          yield pending_whitespace
          pending_whitespace = ""
        produced_any = True
        yield content
    except Exception as e:
      logger.error(f"Unexpected error during streaming: {e}", exc_info=True)
      if produced_any:
        # Already streamed part of the answer; surface the error inline.
        yield "\n\n[Error: Unexpected error occurred]"
        return
      # Nothing emitted yet, fall through to the retry below.
      continue

    if produced_any:
      return

    logger.warning(
      "Model returned an empty response (attempt %d/%d)",
      attempt + 1,
      len(EMPTY_RESPONSE_RETRY_TEMPERATURES),
    )

  # Every attempt produced nothing usable; send a clear message instead of an
  # empty bubble so the user knows what happened.
  yield EMPTY_RESPONSE_FALLBACK



# Matches a dangling trailing fragment left when generation is cut off mid-object:
# a trailing comma, or a quoted key optionally followed by a colon but no value.
_TRAILING_JSON_FRAGMENT_RE = re.compile(r'(?:,|"(?:[^"\\]|\\.)*"\s*:?)\s*$')


def _repair_truncated_json(text: str):
  """Best-effort recovery of JSON truncated mid-generation (e.g. hit max_tokens).

  Grammar-constrained completions are valid JSON only if generation finishes; when
  the model is cut off mid-object the closing quotes/braces are missing. This walks
  the structural state from the first ``{``, closes any dangling string, drops an
  incomplete trailing key/value, and appends the missing closers. Returns the
  parsed object, or ``None`` if nothing salvageable is found.
  """
  start = text.find("{")
  if start == -1:
    return None

  in_string = False
  escape = False
  stack = []
  for ch in text[start:]:
    if escape:
      escape = False
    elif ch == "\\":
      escape = in_string  # backslash only escapes inside a string
    elif ch == '"':
      in_string = not in_string
    elif not in_string:
      if ch in "{[":
        stack.append("}" if ch == "{" else "]")
      elif ch in "}]" and stack:
        stack.pop()

  candidate = text[start:]
  if escape:  # a dangling backslash would escape our synthetic closing quote
    candidate = candidate[:-1]
  if in_string:
    candidate += '"'
  closers = "".join(reversed(stack))

  # Close as-is; if that fails, progressively strip an incomplete trailing
  # fragment (the part after the last complete value) and try again.
  trimmed = candidate
  for _ in range(4):
    try:
      return json.loads(trimmed + closers)
    except json.JSONDecodeError:
      stripped = _TRAILING_JSON_FRAGMENT_RE.sub("", trimmed.rstrip()).rstrip().rstrip(",")
      if stripped == trimmed:
        break
      trimmed = stripped
  return None


def _parse_llm_structured_payload(raw: str):
  """Parse the model's JSON object. API uses json_object; ast.literal_eval breaks on real JSON and multiline strings."""
  text = raw.strip()
  if text.startswith("```"):
    lines = text.splitlines()
    body = lines[1:]
    if body and body[-1].strip() == "```":
      body = body[:-1]
    text = "\n".join(body).strip()
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    pass
  start = text.find("{")
  end = text.rfind("}")
  if start != -1 and end != -1 and end > start:
    snippet = text[start : end + 1]
    try:
      return json.loads(snippet)
    except json.JSONDecodeError:
      pass
  # Last resort: the completion was likely cut off mid-object (hit max_tokens).
  repaired = _repair_truncated_json(text)
  if repaired is not None:
    logger.warning("Recovered a truncated structured LLM response via JSON repair")
    return repaired
  raise ValueError("Could not parse structured LLM response as valid JSON")


def get_structured_llm_response(response_format, messages):

  response = CLIENT_LLAMA.create_chat_completion(
      messages=messages,
      response_format={
          "type": "json_object",
          "schema": response_format.model_json_schema(),
      },
      max_tokens=MAX_TOKENS
  )["choices"][0]["message"]["content"]

  payload = _parse_llm_structured_payload(response)
  return response_format.model_validate(payload)


async def get_llm_response_with_tools(messages, tools=None, max_tokens=None):
  """Get a (plain-text) LLM response, with optional tool calling support.

  Args:
    messages: List of message dicts with 'role' and 'content'
    tools: Optional list of tool definitions
    max_tokens: Maximum tokens (optional)

  Returns:
    Dict with 'content', 'role', and optionally 'tool_calls'
  """

  kwargs = {
    "messages": messages
  }
  
  if max_tokens:
    kwargs["max_tokens"] = max_tokens
    
  if tools:
    kwargs["tools"] = tools
    kwargs["tool_choice"] = "auto"
  
  response = CLIENT_LLAMA.create_chat_completion(**kwargs)
  
  message = response["choices"][0]["message"]
  
  result = {
    "role": message["role"],
    "content": message["content"] or "",
  }
  
  tool_calls = message.get("tool_calls")
  if tool_calls:
    result["tool_calls"] = [
      {
        "id": tc["id"],
        "type": tc["type"],
        "function": {
          "name": tc["function"]["name"],
          "arguments": tc["function"]["arguments"]
        }
      }
      for tc in tool_calls
    ]
  
  return result


def create_title_from_messages(messages):

    class CreateTitleFromMessages(BaseModel):
        title: str

    # Only role + string content for the chat API (drop attachmentPath, etc.)
    slim = []
    for m in messages:
        if not isinstance(m, dict) or "role" not in m:
            continue
        c = m.get("content", "")
        if not isinstance(c, str):
            c = ""
        slim.append({"role": m["role"], "content": c})

    if not slim:
        return "New conversation"

    messages = _apply_system_prompt(slim, create_title_from_messages_prompt)

    response = get_structured_llm_response(CreateTitleFromMessages, messages)

    return response.title
