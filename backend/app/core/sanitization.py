"""Input sanitization utilities for user-provided content."""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Control characters that could be used for injection or formatting attacks
# These are non-printable characters that shouldn't be in normal text
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]')

# Potentially dangerous HTML/script tags (for basic protection)
# Note: We're not using bleach here to avoid over-sanitization
DANGEROUS_HTML_PATTERN = re.compile(
    r'<script[^>]*>.*?</script>|<iframe[^>]*>.*?</iframe>|<object[^>]*>.*?</object>',
    re.IGNORECASE | re.DOTALL
)


def sanitize_user_input(text: Optional[str], max_length: int = 50000) -> str:
    """
    Sanitize user input for LLM processing.
    
    This function:
    - Removes control characters (but preserves normal Unicode)
    - Removes dangerous HTML/script tags (but preserves text content)
    - Truncates if too long
    
    Internal whitespace (newlines, indentation, runs of spaces/tabs) is
    deliberately preserved: this is a chat app people paste code and markdown
    into, and collapsing whitespace silently corrupts indentation and paragraph
    structure. The control-character strip and length cap below already cover
    the abuse cases that a whitespace-collapsing rule was meant to address.
    
    Args:
        text: The input text to sanitize
        max_length: Maximum allowed length (default 50k chars)
    
    Returns:
        Sanitized text
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Truncate if too long (prevent DoS via huge inputs)
    if len(text) > max_length:
        logger.warning(f"Input truncated from {len(text)} to {max_length} characters")
        text = text[:max_length]
    
    # Remove control characters (but keep normal Unicode like é, 中文, etc.)
    text = CONTROL_CHAR_PATTERN.sub('', text)
    
    # Remove dangerous HTML/script tags (but keep the text content)
    text = DANGEROUS_HTML_PATTERN.sub('', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


def sanitize_messages(messages: list) -> list:
    """
    Sanitize all user messages in a conversation.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
    
    Returns:
        Sanitized messages list
    """
    if not messages or not isinstance(messages, list):
        return messages
    
    sanitized = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        
        role = msg.get('role', '')
        content = msg.get('content', '')
        
        if role in ['user', 'assistant', 'system'] and isinstance(content, str):
            sanitized_content = sanitize_user_input(content)
            sanitized.append({
                **msg,
                'content': sanitized_content
            })
        elif role in ['user', 'assistant', 'system'] and isinstance(content, list):
            new_parts = []
            for part in content:
                if not isinstance(part, dict):
                    new_parts.append(part)
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    t = part.get("text", "") or ""
                    new_parts.append({
                        **part,
                        "text": sanitize_user_input(t, max_length=200000),
                    })
                else:
                    new_parts.append(part)
            sanitized.append({**msg, "content": new_parts})
        else:
            sanitized.append(msg)
    
    return sanitized