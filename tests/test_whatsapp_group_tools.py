"""Tests for tools/<os>/whatsapp_group.py: rename the current group and delete
specific messages, with the Baileys worker mocked."""

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from database import get_db, init_db, insert_message_history

GROUP = "wa_web:120363000000000000@g.us"
OTHER = "wa_web:999@g.us"
OS_FOLDERS = ("linux", "macos", "windows")


def _module(os_folder="linux"):
    return importlib.import_module(f"tools.{os_folder}.whatsapp_group")


@pytest.fixture
def worker():
    """Mocked Baileys worker: records each POST and answers 200."""
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url.rsplit("/", 1)[1], json))
        return MagicMock(status_code=200)

    with patch("requests.post", post):
        yield calls


@pytest.fixture
def chat():
    init_db()
    ids = {}
    for key, channel, sender, from_me, is_bot in (
        ("ana", GROUP, "ana@s.whatsapp.net", 0, 0),
        ("bot", GROUP, "bot@s.whatsapp.net", 0, 1),
        ("other", OTHER, "ze@s.whatsapp.net", 0, 0),
    ):
        ids[key] = insert_message_history(
            message_id=f"WA-{key}", channel_id=channel, remote_jid=channel.split(":", 1)[1],
            is_group=1, sender_id=sender, sender_name=key, from_me=from_me, is_bot=is_bot,
            content=f"mensagem {key}", msg_timestamp=1793534400,
        )
    with patch("tools.chat_history._current_channel", return_value=(GROUP, None)):
        yield ids


def test_same_tools_on_every_os():
    root = Path(__file__).resolve().parent.parent / "tools"
    sources = {(root / f / "whatsapp_group.py").read_text() for f in OS_FOLDERS}
    assert len(sources) == 1


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_rename_current_group(chat, worker, os_folder):
    out = _module(os_folder).rename_whatsapp_group("  Viagem   2027 ")
    assert out == "Group renamed to 'Viagem 2027'."
    assert worker == [("group_subject", {"jid": "120363000000000000@g.us", "subject": "Viagem 2027"})]


def test_rename_refuses_private_chat(worker):
    with patch("tools.chat_history._current_channel", return_value=("wa_web:5511@s.whatsapp.net", None)):
        assert _module().rename_whatsapp_group("x") == "Error: the current chat is not a group."
    assert worker == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_rename_invalid_name(chat, worker, name):
    assert _module().rename_whatsapp_group(name).startswith("Error:")
    assert worker == []


def test_rename_worker_error(chat):
    response = MagicMock(status_code=500)
    response.json.return_value = {"details": "not-authorized"}
    with patch("requests.post", return_value=response):
        out = _module().rename_whatsapp_group("Novo")
    assert out == "Error renaming the group: HTTP 500 - not-authorized"


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_delete_others_and_own_messages(chat, worker, os_folder):
    out = _module(os_folder).delete_whatsapp_messages([chat["ana"], f"#{chat['bot']}"])
    assert out.splitlines() == [f"#{chat['ana']}: deleted.", f"#{chat['bot']}: deleted."]
    jid = "120363000000000000@g.us"
    assert worker == [
        ("delete", {"jid": jid, "message_id": "WA-ana", "from_me": False,
                    "participant": "ana@s.whatsapp.net"}),
        ("delete", {"jid": jid, "message_id": "WA-bot", "from_me": True}),
    ]


def test_delete_never_touches_another_chat(chat, worker):
    out = _module().delete_whatsapp_messages([chat["other"]])
    assert out == f"#{chat['other']}: not found in this chat."
    assert worker == []


@pytest.mark.parametrize("ids", [[], ["abc"], list(range(1, 22))])
def test_delete_invalid_ids(chat, worker, ids):
    assert _module().delete_whatsapp_messages(ids).startswith("Error:")
    assert worker == []


def test_search_shows_the_ids_delete_takes(chat):
    from tools.linux.chat_search import search_chat_history

    assert f"#{chat['ana']} [" in search_chat_history("mensagem")


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_tools_are_loaded_on_every_os(os_folder):
    import os
    import tools

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(
            os.path.join(os.path.dirname(tools.__file__), os_folder), f"tools.{os_folder}"
        )
        names = {f.__name__ for f in tools.AVAILABLE_TOOLS}
    assert {"rename_whatsapp_group", "delete_whatsapp_messages"} <= names
