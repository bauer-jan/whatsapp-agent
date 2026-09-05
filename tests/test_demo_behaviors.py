"""Regression tests for identity, real scheduling and manual contact replies."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import threading
import json

import pytest

from tools import whatsapp_admin as admin
from tools.tool_manager import ToolManager, SenderRole
from utils.agent_manager import AgentManager
from utils.persona_loader import PersonaLoader
from utils.heartbeat import HeartbeatLoop
from utils.whatsapp_client import WhatsAppClient, WhatsAppMessage
from utils.poll_loop import _route_message
from utils.config import AgentConfig


@pytest.fixture
def environment(tmp_path, monkeypatch):
    client = MagicMock()
    client.client.get_joined_groups.return_value = []
    client._phone_for_jid.side_effect = lambda jid: jid.User if jid.Server == 's.whatsapp.net' else None
    monkeypatch.setattr(admin, '_wa_client', client)
    monkeypatch.setattr(admin, '_persona_dir', tmp_path)
    return client, tmp_path


def contact(name, number, server='s.whatsapp.net'):
    return SimpleNamespace(JID=SimpleNamespace(User=number, Server=server),
                           Info=SimpleNamespace(FullName=name))


def test_bootstrap_does_not_return_after_successful_onboarding(tmp_path):
    loader = PersonaLoader(templates_dir='templates', persona_dir=str(tmp_path / 'persona'))
    loader.ensure_persona_files()
    (loader.persona_dir / 'BOOTSTRAP.md').unlink()
    loader.ensure_persona_files()
    assert not (loader.persona_dir / 'BOOTSTRAP.md').exists()
    assert 'James' in loader.load_admin_prompt()
    assert 'James' in loader.load_public_prompt()


def test_existing_persona_is_preserved_without_restarting_onboarding(tmp_path):
    (tmp_path / 'SOUL.md').write_text('Custom personality')
    loader = PersonaLoader(persona_dir=str(tmp_path))
    loader.ensure_persona_files()
    assert (tmp_path / 'SOUL.md').read_text() == 'Custom personality'
    assert not (tmp_path / 'BOOTSTRAP.md').exists()
    assert 'James' in loader.load_admin_prompt()


def test_failed_bootstrap_remains_for_retry(tmp_path):
    loader = PersonaLoader(persona_dir=str(tmp_path))
    loader.ensure_persona_files()
    original = loader.load_bootstrap()
    loader.ensure_persona_files()
    assert original and loader.load_bootstrap() == original


@pytest.mark.parametrize('content', [
    '# Heartbeat\n## Tasks\n- Joke: every minute',
    '- Joke [every 0 min]: Send a joke',
    '- Joke [every 1 minutes]: Send a joke',
    '- Joke [every 1 min]: ',
    '  - Joke [every 1 min]: Send a joke',
    'Send a joke every minute',
])
def test_invalid_schedule_preserves_previous_tasks(environment, content):
    _, path = environment
    original = '- Existing [every 60 min]: Existing task'
    (path / 'HEARTBEAT.md').write_text(original)
    assert admin.update_heartbeat(content).startswith('Error:')
    assert (path / 'HEARTBEAT.md').read_text() == original


def test_saved_minute_task_becomes_due_and_invokes_agent(environment):
    client, path = environment
    result = admin.update_heartbeat('# Tasks\n- Joke [every 1 min]: Send a short joke to the admin')
    assert '1 task(s)' in result
    loader = PersonaLoader(persona_dir=str(path))
    manager = MagicMock()
    loop = HeartbeatLoop(loader, manager, '123456789')
    loop._reload_tasks()
    task = loop.tasks[0]
    now = datetime.now(timezone.utc)
    assert not loop._is_due(task, now)
    loop._reload_tasks()
    task = loop.tasks[0]
    assert loop._is_due(task, now + timedelta(minutes=1))
    loop._run_task(task, now + timedelta(minutes=1))
    manager.get_or_create.return_value.agent.assert_called_once()
    manager.session_lock.assert_called_with('123456789')
    client.send_message.assert_not_called()  # Scheduling alone does not send.


def test_empty_schedule_removes_all_tasks(environment):
    _, path = environment
    admin.update_heartbeat('- Joke [every 1 min]: Send joke')
    assert '0 task(s)' in admin.update_heartbeat('')
    assert PersonaLoader(persona_dir=str(path)).load_heartbeat_tasks() == []


def test_full_name_miss_returns_candidates_without_sending(environment):
    client, _ = environment
    client.client.contact.get_all_contacts.return_value = [
        contact('Laura A', '111111111'), contact('Laura B', '222222222')]
    result = admin.lookup_contact('Laura Missing')
    assert 'confirm' in result
    assert 'Laura A' in result and 'Laura B' in result
    client.send_message.assert_not_called()


def test_unresolved_lid_keeps_server_and_is_not_a_phone(environment):
    client, _ = environment
    client.client.contact.get_all_contacts.return_value = [contact('Laura', '777777777', 'lid')]
    assert '777777777@lid' in admin.lookup_contact('Laura')


def test_exact_contact_wins_over_partial_duplicate(environment):
    client, _ = environment
    client.client.contact.get_all_contacts.return_value = [
        contact('Laura', '111111111'), contact('Laura Example', '111111111')]
    result = admin.lookup_contact('Laura Example')
    assert 'No exact' not in result
    assert result.count('111111111') == 1


def test_admin_can_read_recent_chat_but_it_does_not_auto_reply(environment):
    _, _path = environment
    with patch('utils.whatsapp_client.NewClient'):
        client = WhatsAppClient()
    message = WhatsAppMessage('222222222', 'Synthetic question', 123,
                              '222222222@s.whatsapp.net', False, False)
    client._recent_messages.append(message)
    manager = MagicMock()
    _route_message(message, manager, AgentConfig(admin_phone='111111111', response_mode='admin_only'))
    manager.get_or_create.assert_not_called()
    with patch.object(admin, '_wa_client', client):
        result = json.loads(admin.read_recent_messages('222222222'))
        assert result['chat_id'] == '222222222'
        assert result['messages'][0]['text'] == 'Synthetic question'
        assert 'write_message' in result['reply_delivery']
        assert 'No recent' in admin.read_recent_messages('333333333')
    client.client.send_message.assert_not_called()
    tm = ToolManager('111111111')
    tm.register_admin_tools(admin.ALL_ADMIN_TOOLS)
    assert admin.read_recent_messages in tm.get_tools(SenderRole.ADMIN)
    assert admin.read_recent_messages not in tm.get_tools(SenderRole.PUBLIC)


def test_buffer_is_bounded_and_reads_only_selected_chat():
    with patch('utils.whatsapp_client.NewClient'):
        client = WhatsAppClient()
    for i in range(1100):
        client._recent_messages.append(WhatsAppMessage('222', str(i), i, '222@s.whatsapp.net', False, False))
    assert len(client._recent_messages) == 1000
    assert len(client.get_recent_messages('222', 3)) == 3
    assert client.get_recent_messages('333') == []


def test_same_session_lock_serializes_heartbeat_and_admin():
    manager = AgentManager('unused', MagicMock(), MagicMock(), MagicMock())
    assert manager.session_lock('+123') is manager.session_lock('123')
    assert manager.session_lock('456') is not manager.session_lock('123')
    lock = manager.session_lock('123')
    acquired = threading.Event()
    with lock:
        worker = threading.Thread(target=lambda: (lock.acquire(), acquired.set(), lock.release()))
        worker.start()
        assert not acquired.wait(0.05)
    worker.join(1)
    assert acquired.is_set()
