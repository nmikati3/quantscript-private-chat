"""Tests for app.api.conversations — file-based conversation CRUD."""

import json

import pytest

from app.api.conversations import (
    create_new_conversation,
    add_message_to_conversation,
    update_conversation_title,
    delete_conversation,
    get_all_conversations,
    get_conversation_by_id,
)


class TestCreateConversation:
    def test_returns_uuid(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        assert len(cid) == 36  # UUID format

    def test_creates_json_file(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        assert (conversations_dir / f"{cid}.json").exists()

    def test_file_has_title_and_timestamps(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        assert data["title"] == "Test title"
        assert "createdAt" in data
        assert "updatedAt" in data
        assert data["messages"] == []


class TestAddMessage:
    def test_appends_message(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        add_message_to_conversation({"conversation_id": cid, "role": "user", "content": "hello"})
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "hello"

    def test_multiple_messages(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        add_message_to_conversation({"conversation_id": cid, "role": "user", "content": "q1"})
        add_message_to_conversation({"conversation_id": cid, "role": "assistant", "content": "a1"})
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        assert len(data["messages"]) == 2

    def test_raises_on_missing_conversation(self, conversations_dir):
        with pytest.raises(ValueError, match="not found"):
            add_message_to_conversation({
                "conversation_id": "00000000-0000-0000-0000-000000000000",
                "role": "user",
                "content": "nope",
            })

    def test_stores_only_attachment_basename(self, conversations_dir):
        # Persistence must keep the bare filename, never the absolute/local path,
        # so conversation history cannot leak directory structure or temp paths.
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        add_message_to_conversation({
            "conversation_id": cid,
            "role": "user",
            "content": "see file",
            "attachmentPath": "/private/var/folders/zz/T/secret_dir/file.pdf",
        })
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        stored = data["messages"][0]
        assert stored.get("attachmentName") == "file.pdf"
        assert "attachmentPath" not in stored

    def test_prefers_explicit_attachment_name(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        add_message_to_conversation({
            "conversation_id": cid,
            "role": "user",
            "content": "see file",
            "attachmentPath": "/tmp/tmp1a2b3c.pdf",
            "attachmentName": "Q3 Report.pdf",
        })
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        assert data["messages"][0]["attachmentName"] == "Q3 Report.pdf"


class TestUpdateTitle:
    def test_updates_title(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        update_conversation_title(cid, "New title")
        data = json.loads((conversations_dir / f"{cid}.json").read_text())
        assert data["title"] == "New title"

    def test_raises_on_missing_conversation(self, conversations_dir):
        with pytest.raises(ValueError, match="not found"):
            update_conversation_title("00000000-0000-0000-0000-000000000000", "nope")


class TestDeleteConversation:
    def test_removes_file(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        assert (conversations_dir / f"{cid}.json").exists()
        delete_conversation(cid)
        assert not (conversations_dir / f"{cid}.json").exists()

    def test_no_error_on_missing(self, conversations_dir):
        delete_conversation("00000000-0000-0000-0000-000000000000")


class TestGetAllConversations:
    def test_empty(self, conversations_dir):
        assert get_all_conversations() == []

    def test_returns_metadata(self, conversations_dir):
        create_new_conversation([{"role": "user", "content": "first"}])
        create_new_conversation([{"role": "user", "content": "second"}])
        result = get_all_conversations()
        assert len(result) == 2
        assert all("id" in c and "title" in c for c in result)

    def test_sorted_by_updated_at(self, conversations_dir):
        cid1 = create_new_conversation([{"role": "user", "content": "old"}])
        cid2 = create_new_conversation([{"role": "user", "content": "new"}])
        update_conversation_title(cid1, "Updated old")
        result = get_all_conversations()
        assert result[0]["id"] == cid1


class TestGetConversationById:
    def test_returns_messages(self, conversations_dir):
        cid = create_new_conversation([{"role": "user", "content": "hi"}])
        add_message_to_conversation({"conversation_id": cid, "role": "user", "content": "hi"})
        result = get_conversation_by_id(cid)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_raises_for_missing(self, conversations_dir):
        with pytest.raises(ValueError):
            get_conversation_by_id("00000000-0000-0000-0000-000000000000")
