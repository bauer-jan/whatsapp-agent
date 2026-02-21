"""Unit tests for is_allowed and poll loop message routing."""

import sys
import time
from unittest.mock import MagicMock


# Mock neonize before importing main (which imports whatsapp_client)
_neonize_mock = MagicMock()
sys.modules.setdefault("neonize", _neonize_mock)
sys.modules.setdefault("neonize.client", _neonize_mock.client)
sys.modules.setdefault("neonize.events", _neonize_mock.events)
sys.modules.setdefault("neonize.utils", _neonize_mock.utils)
sys.modules.setdefault("neonize.utils.jid", _neonize_mock.utils.jid)

from utils.poll_loop import is_allowed, _inject_context, _phone_from_chat_id, run
from utils.whatsapp_client import WhatsAppMessage


def _make_config(**overrides):
    """Create a mock AgentConfig with sensible defaults."""
    cfg = MagicMock()
    cfg.admin_phone = overrides.get("admin_phone", "5511999999999")
    cfg.response_mode = overrides.get("response_mode", "all")
    cfg.whitelist = overrides.get("whitelist", [])
    cfg.poll_interval = overrides.get("poll_interval", 5.0)
    return cfg


class TestIsAllowedAllMode:
    def test_anyone_allowed(self):
        cfg = _make_config(response_mode="all")
        assert is_allowed("111", cfg) is True
        assert is_allowed("222", cfg) is True
        assert is_allowed(cfg.admin_phone, cfg) is True

    def test_empty_sender_allowed(self):
        cfg = _make_config(response_mode="all")
        assert is_allowed("", cfg) is True


class TestPhoneFromChatId:
    def test_extracts_phone_from_whatsapp_jid(self):
        assert _phone_from_chat_id("4915118380901@s.whatsapp.net") == "4915118380901"

    def test_returns_none_for_group_jid(self):
        assert _phone_from_chat_id("120363001@g.us") is None

    def test_returns_none_for_lid_jid(self):
        assert _phone_from_chat_id("5317186310325@lid") is None

    def test_returns_none_for_empty(self):
        assert _phone_from_chat_id("") is None
        assert _phone_from_chat_id(None) is None


class TestIsAllowedAdminOnly:
    def test_admin_allowed(self):
        cfg = _make_config(response_mode="admin_only")
        assert is_allowed(cfg.admin_phone, cfg) is True

    def test_non_admin_blocked(self):
        cfg = _make_config(response_mode="admin_only")
        assert is_allowed("111", cfg) is False

    def test_empty_sender_blocked(self):
        cfg = _make_config(response_mode="admin_only")
        assert is_allowed("", cfg) is False

    def test_lid_sender_allowed_via_chat_id(self):
        """Admin's LID as sender, but chat_id contains admin phone."""
        cfg = _make_config(response_mode="admin_only", admin_phone="4915778953624")
        assert is_allowed("102868895965337", cfg, chat_id="4915778953624@s.whatsapp.net") is True


class TestIsAllowedWhitelist:
    def test_admin_always_allowed(self):
        cfg = _make_config(response_mode="whitelist", whitelist=[])
        assert is_allowed(cfg.admin_phone, cfg) is True

    def test_whitelisted_phone_allowed(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["111", "222"])
        assert is_allowed("111", cfg) is True
        assert is_allowed("222", cfg) is True

    def test_non_whitelisted_blocked(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["111"])
        assert is_allowed("333", cfg) is False

    def test_empty_whitelist_only_admin(self):
        cfg = _make_config(response_mode="whitelist", whitelist=[])
        assert is_allowed("111", cfg) is False
        assert is_allowed(cfg.admin_phone, cfg) is True

    def test_whitelisted_group_allows_any_sender(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["120363001@g.us"])
        # Unknown sender, but group is whitelisted.
        assert is_allowed("333", cfg, chat_id="120363001@g.us") is True

    def test_non_whitelisted_group_blocks(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["120363001@g.us"])
        assert is_allowed("333", cfg, chat_id="999999@g.us") is False

    def test_whitelisted_phone_in_non_whitelisted_group(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["333"])
        # Sender is whitelisted even though group isn't.
        assert is_allowed("333", cfg, chat_id="999999@g.us") is True

    def test_no_chat_id_falls_back_to_sender(self):
        cfg = _make_config(response_mode="whitelist", whitelist=["111"])
        assert is_allowed("111", cfg, chat_id=None) is True
        assert is_allowed("222", cfg, chat_id=None) is False

    def test_lid_sender_allowed_via_chat_id_phone(self):
        """Sender is a LID, but chat_id phone is whitelisted."""
        cfg = _make_config(response_mode="whitelist", whitelist=["4915118380901"])
        assert is_allowed("5317186310325", cfg, chat_id="4915118380901@s.whatsapp.net") is True

    def test_lid_sender_admin_allowed_via_chat_id(self):
        """Admin's LID as sender, chat_id contains admin phone."""
        cfg = _make_config(response_mode="whitelist", admin_phone="4915778953624")
        assert is_allowed("102868895965337", cfg, chat_id="4915778953624@s.whatsapp.net") is True

    def test_lid_sender_non_whitelisted_chat_blocked(self):
        """LID sender with non-whitelisted chat_id phone stays blocked."""
        cfg = _make_config(response_mode="whitelist", whitelist=["111"])
        assert is_allowed("999", cfg, chat_id="888@s.whatsapp.net") is False


class TestIsAllowedUnknownMode:
    def test_unknown_mode_blocks_all(self):
        cfg = _make_config(response_mode="bogus")
        assert is_allowed("111", cfg) is False
        assert is_allowed(cfg.admin_phone, cfg) is False


# ---------------------------------------------------------------------------
# Tests for _inject_context
# ---------------------------------------------------------------------------

class TestInjectContext:
    def test_appends_to_messages_and_session(self):
        session = MagicMock()
        session.agent.messages = []
        session.agent._session_manager = MagicMock()

        _inject_context(session, "hello context")

        assert len(session.agent.messages) == 1
        assert session.agent.messages[0]["role"] == "user"
        assert session.agent.messages[0]["content"] == [{"text": "hello context"}]
        session.agent._session_manager.append_message.assert_called_once()

    def test_no_session_manager_still_appends(self):
        session = MagicMock()
        session.agent.messages = []
        session.agent._session_manager = None

        _inject_context(session, "no persist")

        assert len(session.agent.messages) == 1

    def test_exception_does_not_propagate(self):
        session = MagicMock()
        session.agent.messages = MagicMock(side_effect=Exception("boom"))

        # Should not raise
        _inject_context(session, "fail gracefully")


# ---------------------------------------------------------------------------
# Tests for message routing in poll loop
# ---------------------------------------------------------------------------

def _make_msg(**overrides):
    """Create a WhatsAppMessage with sensible defaults."""
    defaults = dict(
        sender="5511999990000",
        body="test",
        timestamp=int(time.time()) + 60,  # future timestamp so it passes startup filter
        chat_id="5511999990000@s.whatsapp.net",
        is_group=False,
        is_from_me=False,
    )
    defaults.update(overrides)
    return WhatsAppMessage(**defaults)


def _run_one_iteration(msgs, config=None, session_manager=None, wa_client=None):
    """Run a single poll loop iteration with the given messages."""
    stop = [False]
    call_count = [0]

    def fake_get_new_messages():
        call_count[0] += 1
        if call_count[0] == 1:
            return msgs
        stop[0] = True
        return []

    if wa_client is None:
        wa_client = MagicMock()
    wa_client.get_new_messages = fake_get_new_messages

    if config is None:
        config = _make_config(response_mode="all")

    if session_manager is None:
        session_manager = MagicMock()
        mock_session = MagicMock()
        mock_session.agent.return_value = "ok"
        mock_session.agent.messages = []
        mock_session.agent._session_manager = MagicMock()
        session_manager.get_or_create.return_value = mock_session

    config.poll_interval = 0

    run(wa_client, session_manager, config, shutdown_flag=lambda: stop[0])

    return wa_client, session_manager


class TestOwnGroupMessages:
    def test_own_group_message_injects_context_not_reply(self):
        msg = _make_msg(is_group=True, is_from_me=True, chat_id="123@g.us", body="hey group")
        wa, sm = _run_one_iteration([msg])

        # Should create session for admin phone (context injection)
        sm.get_or_create.assert_called()
        # Should NOT send any message back
        wa.send_message.assert_not_called()


class TestOwnDmMessages:
    def test_own_dm_to_other_injects_context_not_reply(self):
        msg = _make_msg(
            is_group=False, is_from_me=True,
            sender="5511999990000",
            chat_id="5511888880000@s.whatsapp.net",
            body="hey david",
        )
        wa, sm = _run_one_iteration([msg])

        # Should NOT send any message back
        wa.send_message.assert_not_called()

    def test_self_chat_gets_agent_response(self):
        """Admin messaging their own number = talking to the agent."""
        admin = "5511999990000"
        msg = _make_msg(
            is_group=False, is_from_me=True,
            sender=admin,
            chat_id=f"{admin}@s.whatsapp.net",
            body="hello agent",
        )
        config = _make_config(response_mode="all", admin_phone=admin)

        mock_session = MagicMock()
        mock_session.agent.return_value = "hi there"
        mock_session.agent.messages = []
        mock_session.agent._session_manager = MagicMock()

        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Agent should have been called with context-prefixed prompt
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert "hello agent" in prompt
        assert admin in prompt


class TestNormalIncoming:
    def test_incoming_dm_gets_response(self):
        admin = "5511999990000"
        msg = _make_msg(
            is_group=False, is_from_me=False,
            sender="5511888880000",
            chat_id="5511888880000@s.whatsapp.net",
            body="hi",
        )
        config = _make_config(response_mode="all", admin_phone=admin)

        mock_session = MagicMock()
        mock_session.agent.return_value = "hello"
        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Agent called with context-prefixed prompt
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert "hi" in prompt
        assert "5511888880000" in prompt
        # Poll loop no longer auto-forwards — agent uses write_message tool
        wa.send_message.assert_not_called()

    def test_incoming_group_msg_replies_to_group(self):
        admin = "5511999990000"
        msg = _make_msg(
            is_group=True, is_from_me=False,
            sender="5511888880000",
            chat_id="123@g.us",
            body="yo",
        )
        config = _make_config(response_mode="all", admin_phone=admin)

        mock_session = MagicMock()
        mock_session.agent.return_value = "sup"
        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Agent called with context including group chat_id
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert "yo" in prompt
        assert "123@g.us" in prompt
        # Poll loop no longer auto-forwards
        wa.send_message.assert_not_called()


class TestLidResolution:
    """Messages arriving with a LID sender should be resolved to the phone from chat_id."""

    def test_lid_sender_resolved_to_phone_in_dm(self):
        """Marcel's LID gets resolved to his phone number from chat_id."""
        admin = "4915778953624"
        lid = "5317186310325"
        real_phone = "4915118380901"
        msg = _make_msg(
            is_group=False, is_from_me=False,
            sender=lid,
            chat_id=f"{real_phone}@s.whatsapp.net",
            body="HAHAH",
        )
        config = _make_config(
            response_mode="whitelist", admin_phone=admin,
            whitelist=[real_phone],
        )

        mock_session = MagicMock()
        mock_session.agent.return_value = "lol"
        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Agent should be called with the resolved phone, not the LID
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert real_phone in prompt
        assert lid not in prompt
        # Session created for the real phone
        sm.get_or_create.assert_called_once_with(real_phone, reply_to=real_phone)

    def test_admin_lid_resolved_for_self_chat(self):
        """Admin's LID sender + admin chat_id = routes to admin session."""
        admin = "4915778953624"
        admin_lid = "102868895965337"
        msg = _make_msg(
            is_group=False, is_from_me=False,
            sender=admin_lid,
            chat_id=f"{admin}@s.whatsapp.net",
            body="hello agent",
        )
        config = _make_config(response_mode="whitelist", admin_phone=admin)

        mock_session = MagicMock()
        mock_session.agent.return_value = "hi"
        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Should route to admin session with resolved phone
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert admin in prompt
        assert admin_lid not in prompt

    def test_lid_not_resolved_for_groups(self):
        """Group messages don't get LID resolution (chat_id is group JID)."""
        admin = "5511999990000"
        msg = _make_msg(
            is_group=True, is_from_me=False,
            sender="5317186310325",
            chat_id="123@g.us",
            body="group msg",
        )
        config = _make_config(response_mode="all", admin_phone=admin)

        mock_session = MagicMock()
        mock_session.agent.return_value = "ok"
        sm = MagicMock()
        sm.get_or_create.return_value = mock_session

        wa, sm = _run_one_iteration([msg], config=config, session_manager=sm)

        # Sender stays as-is for groups (no @s.whatsapp.net in chat_id)
        mock_session.agent.assert_called_once()
        prompt = mock_session.agent.call_args[0][0]
        assert "5317186310325" in prompt
