import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.core.paths import resolve_conversations_storage_path
from app.engine.llm.inference import create_title_from_messages

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Timezone-aware UTC timestamp, formatted with a trailing 'Z' for back-compat."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


CONVERSATIONS_STORAGE_PATH = resolve_conversations_storage_path()

# Ensure storage directory exists
CONVERSATIONS_STORAGE_PATH.mkdir(parents=True, exist_ok=True)


def _get_conversation_file_path(conversation_id):
    """Get the file path for a conversation."""
    return CONVERSATIONS_STORAGE_PATH / f"{conversation_id}.json"


def _load_conversation(conversation_id):
    """Load a conversation from disk."""
    file_path = _get_conversation_file_path(conversation_id)
    if not file_path.exists():
        return None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_conversation(conversation_id, data):
    """Save a conversation to disk."""
    file_path = _get_conversation_file_path(conversation_id)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def create_new_conversation(messages):
    """Create a new conversation and return its ID."""

    title = create_title_from_messages(messages)

    conversation_id = str(uuid.uuid4())
    now = _utc_now_iso()

    conversation_data = {
        "title": title,
        "createdAt": now,
        "updatedAt": now,
        "messages": [],
    }

    _save_conversation(conversation_id, conversation_data)
    return conversation_id


def add_message_to_conversation(message):
    """Add a message to a conversation."""
    conversation_id = message['conversation_id']
    conversation = _load_conversation(conversation_id)
    
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    
    now = _utc_now_iso()
    
    # Prepare message data
    message_data = {
        "role": message['role'],
        "content": message['content'],
        "createdAt": now,
    }
    # Persist only the bare filename for display, never an absolute/local path.
    # The live temp path (``attachmentPath``) is used at request time but must
    # not be written to conversation history, where it would leak the user's
    # directory structure and stay long after the temp file is cleaned up.
    attachment_name = message.get("attachmentName") or message.get("attachmentPath")
    if attachment_name:
        message_data["attachmentName"] = Path(attachment_name).name

    conversation['messages'].append(message_data)
    conversation['updatedAt'] = now
    
    _save_conversation(conversation_id, conversation)


def update_conversation_title(conversation_id, new_title):
    """Update the title of a conversation."""
    conversation = _load_conversation(conversation_id)
    
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    
    conversation['title'] = new_title
    conversation['updatedAt'] = _utc_now_iso()
    
    _save_conversation(conversation_id, conversation)


def delete_conversation(conversation_id):
    """Delete a conversation."""
    file_path = _get_conversation_file_path(conversation_id)
    if file_path.exists():
        file_path.unlink()


def get_all_conversations():
    """Get all conversations."""
    conversations = []
    for file_path in CONVERSATIONS_STORAGE_PATH.glob("*.json"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                conversation = json.load(f)
                conversations.append({
                    'id': file_path.stem,  # filename without extension
                    'title': conversation.get('title', ''),
                    'createdAt': conversation.get('createdAt', ''),
                    'updatedAt': conversation.get('updatedAt', ''),
                })
        except Exception as e:
            logger.error(f"Error loading conversation from {file_path}: {e}")
            continue
    
    # Sort by updatedAt descending (most recent first)
    conversations.sort(key=lambda x: x.get('updatedAt', ''), reverse=True)
    return conversations


def get_conversation_by_id(conversation_id):
    """Get all messages for a conversation.

    Raises:
        ValueError: if no conversation exists with the given id. (An existing
        conversation with no messages returns an empty list, not an error.)
    """
    conversation = _load_conversation(conversation_id)

    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    messages = conversation.get('messages', [])
    
    # Convert message format to match expected structure
    result = []
    for msg in messages:
        message_dict = {
            'role': msg.get('role', ''),
            'content': msg.get('content', ''),
            'createdAt': msg.get('createdAt', ''),
        }
        # Back-compat: older conversations stored the absolute ``attachmentPath``.
        # Surface only the basename so historical data can no longer leak a path.
        attachment_name = msg.get('attachmentName') or msg.get('attachmentPath')
        if attachment_name:
            message_dict['attachmentName'] = Path(attachment_name).name
        result.append(message_dict)
    
    return result