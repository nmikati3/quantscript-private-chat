import os
import gc
from app.engine.llm.prompts import create_title_from_messages_prompt, write_web_search_query_prompt
from pydantic import BaseModel
import logging
from llama_cpp import Llama
from app.engine.llm.prompts import compute_web_search_system_prompt, write_web_search_query_prompt, text_response_prompt
from app.engine.llm.web_search import web_search_and_fetch_articles
import json
from llama_cpp.llama_chat_format import Llava16ChatHandler
from app.engine.llm.model_download import download_model_files, download_mmproj
from app.core.startup_state import is_ready, set_phase_progress

logger = logging.getLogger(__name__)

MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
CHAT_HISTORY_MAX_MESSAGES = int(os.environ.get("CHAT_HISTORY_MAX_MESSAGES", "5"))

LLAMA_REPO_ID = os.environ.get("LLAMA_REPO_ID","unsloth/gemma-4-E4B-it-GGUF")
LLAMA_FILENAME = os.environ.get("LLAMA_FILENAME","gemma-4-E4B-it-Q8_0.gguf")
N_CTX = int(os.environ.get("N_CTX", "32768"))
LLAMA_MMPROJ_FILENAME = os.environ.get("LLAMA_MMPROJ_FILENAME","mmproj-F16.gguf")

MMPROJ_PATH: str | None = None
CHAT_HANDLER = None
CLIENT_LLAMA = None


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


def _get_chat_handler():
    global CHAT_HANDLER
    if CHAT_HANDLER is None:
        report = not is_ready()
        CHAT_HANDLER = Llava16ChatHandler(
            clip_model_path=_ensure_mmproj_path(report_progress=report),
            verbose=False,
        )
    return CHAT_HANDLER


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
    global CLIENT_LLAMA, CHAT_HANDLER

    _close_resource(CLIENT_LLAMA, "LLM client")
    CLIENT_LLAMA = None

    _close_resource(CHAT_HANDLER, "chat handler")
    CHAT_HANDLER = None

    gc.collect()


def initialize_llama(deep_research=False):
    global CLIENT_LLAMA, MMPROJ_PATH, CHAT_HANDLER

    if not LLAMA_REPO_ID or not LLAMA_FILENAME:
        raise RuntimeError("LLAMA_REPO_ID and LLAMA_FILENAME must be set")

    _unload_llama()

    report_progress = not is_ready()
    phase_id = "llm"

    main_path, mmproj_path = download_model_files(
        phase_id,
        LLAMA_REPO_ID,
        main_filename=LLAMA_FILENAME,
        mmproj_filename=LLAMA_MMPROJ_FILENAME if not deep_research else None,
        report_progress=report_progress,
    )
    if mmproj_path:
        MMPROJ_PATH = mmproj_path

    if report_progress:
        set_phase_progress(phase_id, percent=99, detail="Loading model into memory…")

    if deep_research: # Deep research uses function calling that is not supported in the chat handler, so we need to use the chat format "chatml-function-calling".
        CLIENT_LLAMA = Llama( # chatml-function-calling does not support images so we only use it for deep research
            model_path=main_path,
            n_ctx=N_CTX,
            n_gpu_layers=-1,
            flash_attn=True,
            chat_format="chatml-function-calling",
            verbose=False,
        )
    else:
        CLIENT_LLAMA = Llama(
            model_path=main_path,
            n_ctx=N_CTX,
            n_gpu_layers=-1,
            flash_attn=True,
            chat_handler=_get_chat_handler(),
            verbose=False,
        )

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

    messages = slim[:-1] + [{"role": "system", "content": write_web_search_query_prompt}] + slim[-1:]

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

  if search:
    system_prompt = web_search_system_prompt(messages)
  else:
    system_prompt = text_response_prompt

  messages = messages[:-1] + [{"role": "system", "content": system_prompt}] + messages[-1:]

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
  """Get LLM response with optional tool calling support.
  
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

    messages = slim[:-1] + [{"role": "system", "content": create_title_from_messages_prompt}] + slim[-1:]

    response = get_structured_llm_response(CreateTitleFromMessages, messages)

    return response.title
