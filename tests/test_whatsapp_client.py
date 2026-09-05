"""Unit and property tests for WhatsAppClient (Tasks 2.2, 2.3).

WhatsAppClient wraps neonize which requires native bindings (libmagic).
We mock the neonize imports at the module level so tests can run in CI
without the native library installed.
"""

import queue
import sys
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Mock neonize before importing whatsapp_client — neonize requires libmagic
# which may not be available in test environments.
# ---------------------------------------------------------------------------
_neonize_mock = MagicMock()
sys.modules.setdefault("neonize", _neonize_mock)
sys.modules.setdefault("neonize.client", _neonize_mock.client)
sys.modules.setdefault("neonize.events", _neonize_mock.events)
sys.modules.setdefault("neonize.utils", _neonize_mock.utils)
sys.modules.setdefault("neonize.utils.jid", _neonize_mock.utils.jid)

from utils.whatsapp_client import WhatsAppMessage, WhatsAppClient, normalize_phone


# ---------------------------------------------------------------------------
# Property test: message parsing preserves all fields (Property 1)
# Feature: whatsapp-agent, Property 1: Polled message parsing preserves all fields
# ---------------------------------------------------------------------------

phone_st = st.from_regex(r"[1-9]\d{7,14}", fullmatch=True)
body_st = st.text(min_size=1, max_size=500)
timestamp_st = st.integers(min_value=0, max_value=2**31 - 1)
chat_id_st = st.text(min_size=1, max_size=100)
is_group_st = st.booleans()


@given(
    sender=phone_st,
    body=body_st,
    timestamp=timestamp_st,
    chat_id=chat_id_st,
    is_group=is_group_st,
    is_from_me=st.booleans(),
)
@settings(max_examples=100)
def test_property_message_fields_preserved(sender, body, timestamp, chat_id, is_group, is_from_me):
    """Property 1: constructing a WhatsAppMessage preserves all fields exactly."""
    msg = WhatsAppMessage(
        sender=sender, body=body, timestamp=timestamp,
        chat_id=chat_id, is_group=is_group, is_from_me=is_from_me,
    )
    assert msg.sender == sender
    assert msg.body == body
    assert msg.timestamp == timestamp
    assert msg.chat_id == chat_id
    assert msg.is_group == is_group
    assert msg.is_from_me == is_from_me


# ---------------------------------------------------------------------------
# Unit tests for WhatsAppClient (Task 2.3)
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_strips_non_digits(self):
        assert normalize_phone("+55 (11) 99999-9999") == "5511999999999"

    def test_already_digits(self):
        assert normalize_phone("5511999999999") == "5511999999999"

    def test_empty_string(self):
        assert normalize_phone("") == ""


class TestWhatsAppClientQueueDrain:
    """Test get_new_messages drains the inbox queue correctly."""

    def test_get_new_messages_returns_queued(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client._inbox = queue.Queue()
        client._connected = False

        msg1 = WhatsAppMessage("111", "hello", 1000, "chat1", False, False)
        msg2 = WhatsAppMessage("222", "world", 1001, "chat2", True, False)
        client._inbox.put(msg1)
        client._inbox.put(msg2)

        result = client.get_new_messages()
        assert len(result) == 2
        assert result[0].body == "hello"
        assert result[1].body == "world"

    def test_get_new_messages_empty_queue(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client._inbox = queue.Queue()
        client._connected = False

        assert client.get_new_messages() == []


class TestWhatsAppClientConnectionStatus:
    """Test connection status tracking."""

    def test_initially_disconnected(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client._connected = False
        assert client.is_connected() is False

    def test_connected_after_flag_set(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client._connected = True
        assert client.is_connected() is True


class TestNativeShutdown:
    def test_shutdown_cancels_native_context_and_joins_connection_thread(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.client = MagicMock()
        client._connected = True
        thread = MagicMock()
        thread.is_alive.return_value = False
        client._connection_thread = thread
        client.disconnect()
        client.client.stop.assert_called_once()
        client.client.disconnect.assert_not_called()
        thread.join.assert_called_once_with(timeout=5)
        assert client._connection_thread is None
        assert not client.is_connected()

    def test_shutdown_before_connection_thread_starts(self):
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.client = MagicMock()
        client._connection_thread = None
        client._connected = False
        client.disconnect()
        client.client.stop.assert_called_once()
