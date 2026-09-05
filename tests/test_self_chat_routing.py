"""Regression coverage for LID self-chat routing and bootstrap-time replies."""
import queue
import threading
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import utils.whatsapp_client as transport
from utils.config import AgentConfig
from utils.poll_loop import _route_message, run


def jid(user='', server=''):
    return SimpleNamespace(User=user, Server=server)


def make_wrapper():
    wrapper = transport.WhatsAppClient.__new__(transport.WhatsAppClient)
    wrapper.client = MagicMock()
    wrapper.client.get_pn_from_lid.return_value = jid()
    wrapper._inbox = queue.Queue()
    wrapper._recent_messages = deque(maxlen=1000)
    wrapper._recent_lock = threading.Lock()
    wrapper._connected = True
    callbacks = {}

    def register(kind):
        def bind(callback):
            callbacks[kind] = callback
            return callback
        return bind

    wrapper.client.event.side_effect = register
    wrapper._register_handlers()
    return wrapper, callbacks[transport.MessageEv]


def event(sender, chat, sender_alt=None, recipient_alt=None, own=True):
    source = SimpleNamespace(Sender=sender, Chat=chat, SenderAlt=sender_alt or jid(),
                             RecipientAlt=recipient_alt or jid(), IsFromMe=own, IsGroup=False)
    return SimpleNamespace(Info=SimpleNamespace(MessageSource=source, Timestamp=110),
                           Message=SimpleNamespace(conversation='synthetic hello'))


def test_lid_self_chat_maps_to_admin_and_invokes_agent():
    wrapper, callback = make_wrapper()
    wrapper.client.get_pn_from_lid.return_value = jid('123456789', 's.whatsapp.net')
    callback(wrapper.client, event(jid('987654321', 'lid'), jid('987654321', 'lid')))
    message = wrapper.get_new_messages()[0]
    assert message.sender == '123456789'
    assert message.chat_id == '123456789@s.whatsapp.net'
    with patch('utils.poll_loop._handle_incoming') as handle:
        _route_message(message, MagicMock(), AgentConfig(admin_phone='123456789', response_mode='admin_only'))
    handle.assert_called_once()
    assert handle.call_args.args[0].sender == '123456789'


def test_own_dm_resolves_recipient_separately_from_admin_sender():
    wrapper, callback = make_wrapper()
    callback(wrapper.client, event(jid('900', 'lid'), jid('901', 'lid'),
        sender_alt=jid('123456789', 's.whatsapp.net'),
        recipient_alt=jid('234567891', 's.whatsapp.net')))
    message = wrapper.get_new_messages()[0]
    assert message.sender == '123456789'
    assert message.chat_id == '234567891@s.whatsapp.net'
    with patch('utils.poll_loop._handle_incoming') as handle:
        _route_message(message, MagicMock(), AgentConfig(admin_phone='123456789', response_mode='admin_only'))
    handle.assert_not_called()


def test_unresolved_lid_is_not_relabelled_as_admin_phone():
    wrapper, callback = make_wrapper()
    callback(wrapper.client, event(jid('123456789', 'lid'), jid('123456789', 'lid')))
    message = wrapper.get_new_messages()[0]
    assert message.sender == '123456789@lid'
    assert message.chat_id == '123456789@lid'
    with patch('utils.poll_loop._handle_incoming') as handle:
        _route_message(message, MagicMock(), AgentConfig(admin_phone='123456789', response_mode='admin_only'))
    handle.assert_not_called()


@pytest.mark.parametrize('timestamp,should_route', [(110, True), (99, False)])
def test_startup_filter_uses_launch_boundary_not_poll_start(timestamp, should_route):
    client = MagicMock()
    message = transport.WhatsAppMessage('123456789','synthetic',timestamp,'123456789@s.whatsapp.net',False,True)
    client.get_new_messages.return_value = [message]
    iterations = iter([False, True])
    with patch('utils.poll_loop.time.sleep'), patch('utils.poll_loop.time.time', return_value=200), \
         patch('utils.poll_loop._route_message') as route:
        run(client, MagicMock(), AgentConfig(admin_phone='123456789'),
            shutdown_flag=lambda: next(iterations), startup_ts=100)
    assert route.called == should_route


def test_received_message_is_readable_after_inbox_is_drained():
    wrapper, callback = make_wrapper()
    callback(wrapper.client, event(jid('222222222', 's.whatsapp.net'),
                                  jid('222222222', 's.whatsapp.net'), own=False))
    drained = wrapper.get_new_messages()
    assert len(drained) == 1
    assert wrapper.get_new_messages() == []
    assert wrapper.get_recent_messages('222222222') == drained
