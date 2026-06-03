from app.engine.llm.inference import trim_chat_messages


def test_trim_chat_messages_keeps_short_history():
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    assert trim_chat_messages(messages, max_messages=20) == messages


def test_trim_chat_messages_drops_system_and_keeps_recent_turns():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(25):
        messages.append({"role": "user", "content": f"u{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})

    trimmed = trim_chat_messages(messages, max_messages=6)
    system = [m for m in trimmed if m["role"] == "system"]
    non_system = [m for m in trimmed if m["role"] != "system"]

    # System messages are dropped on trim; the chat path re-applies its own
    # system prompt afterwards (see stream_llm_response).
    assert len(system) == 0
    assert len(non_system) == 6
    assert non_system[-1]["content"] == "a24"
    assert non_system[-2]["content"] == "u24"
