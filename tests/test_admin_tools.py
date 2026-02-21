"""Unit tests for admin tools and reply tool factory."""

import sys
from unittest.mock import MagicMock

import pytest

# Mock neonize before importing admin tools
_neonize_mock = MagicMock()
sys.modules.setdefault("neonize", _neonize_mock)
sys.modules.setdefault("neonize.client", _neonize_mock.client)
sys.modules.setdefault("neonize.events", _neonize_mock.events)
sys.modules.setdefault("neonize.utils", _neonize_mock.utils)
sys.modules.setdefault("neonize.utils.jid", _neonize_mock.utils.jid)

from tools.whatsapp_admin import (
    init as init_admin,
    write_message,
    update_soul,
    update_user_profile,
    update_heartbeat,
)
from tools.whatsapp_public import make_reply_tool


@pytest.fixture
def setup_tools(tmp_path):
    """Initialize tools with mocked dependencies."""
    wa_client = MagicMock()
    wa_client.send_message.return_value = True

    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()

    init_admin(wa_client=wa_client, persona_dir=str(persona_dir))
    return wa_client, persona_dir


class TestWriteMessage:
    def test_sends_message(self, setup_tools):
        wa_client, _ = setup_tools
        result = write_message(phone="222", message="hello")
        wa_client.send_message.assert_called_once_with("222", "hello")
        assert "sent" in result.lower()


class TestUpdatePersonaTools:
    def test_update_soul(self, setup_tools):
        _, persona_dir = setup_tools
        result = update_soul(content="new soul")
        assert "Updated" in result
        assert (persona_dir / "SOUL.md").read_text() == "new soul"

    def test_update_user_profile(self, setup_tools):
        _, persona_dir = setup_tools
        result = update_user_profile(content="new profile")
        assert "Updated" in result
        assert (persona_dir / "USER.md").read_text() == "new profile"

    def test_update_heartbeat(self, setup_tools):
        _, persona_dir = setup_tools
        result = update_heartbeat(content="- Task [every 5 min]: do stuff")
        assert "Updated" in result
        assert (persona_dir / "HEARTBEAT.md").read_text() == "- Task [every 5 min]: do stuff"


class TestMakeReplyTool:
    def test_reply_sends_to_baked_in_chat(self):
        wa_client = MagicMock()
        wa_client.send_message.return_value = True
        reply = make_reply_tool(wa_client, "5511888880000")
        result = reply(message="hi")
        wa_client.send_message.assert_called_once_with("5511888880000", "hi")
        assert "replied" in result.lower()

    def test_reply_reports_failure(self):
        wa_client = MagicMock()
        wa_client.send_message.return_value = False
        reply = make_reply_tool(wa_client, "5511888880000")
        result = reply(message="hi")
        assert "failed" in result.lower()

    def test_different_closures_target_different_chats(self):
        wa_client = MagicMock()
        wa_client.send_message.return_value = True
        reply_a = make_reply_tool(wa_client, "111")
        reply_b = make_reply_tool(wa_client, "222")
        reply_a(message="a")
        reply_b(message="b")
        calls = wa_client.send_message.call_args_list
        assert calls[0].args == ("111", "a")
        assert calls[1].args == ("222", "b")
