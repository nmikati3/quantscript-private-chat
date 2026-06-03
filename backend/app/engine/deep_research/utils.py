"""Utility functions for deep research without LangChain dependencies."""

import pandas as pd
from typing import List, Dict, Any, Optional

def get_today_str() -> str:
    """Get today's date as a string."""
    return str(pd.Timestamp.now())[:10]


def get_buffer_string(messages: List[Dict[str, Any]]) -> str:
    """Convert messages list to a string representation."""
    result = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            result.append(f"{role}: {content}")
    return "\n".join(result)


def filter_messages(messages: List[Dict[str, Any]], include_types: List[str] = None) -> List[Dict[str, Any]]:
    """Filter messages by type. include_types can be 'user', 'assistant', 'system', 'tool'."""
    if include_types is None:
        return messages
    
    filtered = []
    for msg in messages:
        role = msg.get("role", "")
        if role in include_types or (role == "assistant" and "ai" in include_types):
            filtered.append(msg)
    return filtered


def remove_up_to_last_ai_message(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove messages up to and including the last assistant message."""
    result = []
    found_last_ai = False
    
    # Iterate backwards to find the last assistant message
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant" and not found_last_ai:
            found_last_ai = True
            continue
        if found_last_ai:
            result.insert(0, messages[i])
    
    return result if found_last_ai else messages


def is_token_limit_exceeded(error: Exception) -> bool:
    """Check if error is due to token limit exceeded."""
    error_str = str(error).lower()
    token_errors = [
        "token",
        "context length",
        "maximum context length",
        "exceeds maximum",
        "too many tokens"
    ]
    return any(term in error_str for term in token_errors)


def get_all_tools() -> List[Dict[str, Any]]:
    """Get all available tools for research. Returns list of tool definitions."""
    # Define think_tool
    think_tool = {
        "type": "function",
        "function": {
            "name": "think_tool",
            "description": """Tool for strategic reflection on research progress and decision-making.

Use this tool after each search to analyze results and plan next steps systematically.
This creates a deliberate pause in the research workflow for quality decision-making.

When to use:
- After receiving search results: What key information did I find?
- Before deciding next steps: Do I have enough to answer comprehensively?
- When assessing research gaps: What specific information am I still missing?
- Before concluding research: Can I provide a complete answer now?

Reflection should address:
1. Analysis of current findings - What concrete information have I gathered?
2. Gap assessment - What crucial information is still missing?
3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
4. Strategic decision - Should I continue searching or provide my answer?""",
            "parameters": {
                "type": "object",
                "properties": {
                    "reflection": {
                        "type": "string",
                        "description": "Your detailed reflection on research progress, findings, gaps, and next steps"
                    }
                },
                "required": ["reflection"]
            }
        }
    }
    
    web_search_tool = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information relevant to the research query. Returns articles and their contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant web pages and articles."
                    }
                },
                "required": ["query"]
            }
        }
    }

    return [think_tool, web_search_tool]


def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making."""
    return f"Reflection recorded: {reflection}"