"""Runtime facts, startup notice and metadata-only tool execution evidence."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.tool_manager import ToolManager
from utils.agent_manager import AgentManager
from utils.config import AgentConfig, MCPServerConfig, ModelConfig
from utils.heartbeat import HeartbeatLoop
from utils.mcp_manager import MCPManager
from utils.persona_loader import PersonaLoader
from utils.tool_audit import ToolAudit
import main


def server_state(status='started'):
    return {'name': 'example-source', 'transport': 'stdio', 'role': 'admin',
            'status': status, 'tools': ['get_overview'] if status == 'started' else []}


def test_admin_runtime_facts_and_tool_refresh_without_public_leak(tmp_path):
    (tmp_path / 'SOUL.md').write_text('You are James.')
    (tmp_path / 'USER.md').write_text('Private user background')
    loader = PersonaLoader(persona_dir=str(tmp_path))
    tm = ToolManager('111111111')
    tm.register_admin_tools([SimpleNamespace(tool_name='get_overview')])
    tm.register_public_tools([])
    state = {'mcp_inventory_available': True, 'mcp_servers': [server_state()],
             'heartbeat': {'running': True, 'configured_tasks': []}}
    provider = MagicMock(side_effect=lambda: state)
    manager = AgentManager(str(tmp_path / 'sessions'), loader, tm, MagicMock(),
                           ModelConfig(provider='openai', model_id='test-model'), provider)
    with patch('utils.agent_manager.Agent') as agent, \
         patch('utils.agent_manager.FileSessionManager'), \
         patch('utils.agent_manager.create_model'):
        manager.get_or_create('111111111')
        kwargs = agent.call_args.kwargs
        assert 'example-source' in kwargs['system_prompt']
        assert 'Application runtime facts' in kwargs['system_prompt']
        assert 'test-model' in kwargs['system_prompt']
        status_tool = next(t for t in kwargs['tools'] if t.tool_name == 'get_runtime_status')
        actual = json.loads(status_tool())
        assert set(actual['available_tools']) == {'get_overview', 'get_runtime_status', 'reply'}
        state['mcp_servers'] = [server_state('stopped')]
        assert json.loads(status_tool())['mcp_servers'][0]['status'] == 'stopped'
        provider.reset_mock()
        manager.get_or_create('222222222')
        public = agent.call_args.kwargs
        assert 'Private user background' not in public['system_prompt']
        assert 'example-source' not in public['system_prompt']
        assert 'get_runtime_status' not in {t.tool_name for t in public['tools']}
        provider.assert_not_called()


def test_mcp_snapshot_reports_failures_and_never_includes_connection_secrets():
    cfg = MCPServerConfig(name='private-server', transport='stdio', command='/secret/path',
                          env={'TOKEN': 'SYNTHETIC_SECRET'}, args=('SYNTHETIC_ARG',))
    with patch('utils.mcp_manager.MCPClient') as cls:
        cls.return_value.start.side_effect = RuntimeError('SYNTHETIC_SECRET')
        manager = MCPManager([cfg])
        manager.start_all()
    snapshot = manager.status_snapshot()
    assert snapshot[0]['status'] == 'failed'
    output = json.dumps(snapshot)
    for excluded in ['SYNTHETIC_SECRET', 'SYNTHETIC_ARG', '/secret/path', 'TOKEN']:
        assert excluded not in output
    snapshot[0]['tools'].append('fake')
    assert manager.status_snapshot()[0]['tools'] == []


def test_startup_notice_is_sent_without_model_and_distinguishes_failed_servers():
    config = AgentConfig(admin_phone='111111111')
    client = MagicMock()
    client.send_message.return_value = True
    mcp = MagicMock()
    mcp.status_snapshot.return_value = [server_state(), dict(server_state('failed'), name='other-source')]
    heartbeat = MagicMock()
    heartbeat.status_snapshot.return_value = {'configured_tasks': []}
    with patch('utils.agent_manager.Agent') as agent:
        assert main._send_startup_notice(config, client, mcp, heartbeat)
        agent.assert_not_called()
    client.send_message.assert_called_once()
    recipient, message = client.send_message.call_args.args
    assert recipient == config.admin_phone
    assert 'James is online' in message and 'example-source (1 tools)' in message
    assert 'MCP unavailable: other-source' in message


def test_startup_send_failure_is_not_reported_as_success(caplog):
    caplog.set_level(logging.INFO)
    client = MagicMock()
    client.send_message.return_value = False
    mcp = MagicMock()
    mcp.status_snapshot.return_value = []
    heartbeat = MagicMock()
    heartbeat.status_snapshot.return_value = {'configured_tasks': []}
    assert not main._send_startup_notice(AgentConfig(admin_phone='111111111'), client, mcp, heartbeat)
    assert 'could not be sent' in caplog.text
    assert 'Startup notice sent to admin' not in caplog.text


def test_normal_restart_sends_ready_notice_and_cleans_up(tmp_path):
    config = AgentConfig(admin_phone='111111111', persona_dir=str(tmp_path))
    client = MagicMock()
    mcp = MagicMock()
    mcp.status_snapshot.return_value = [server_state()]
    mcp.get_admin_tools.return_value = []
    mcp.get_public_tools.return_value = []
    heartbeat = MagicMock()
    heartbeat.status_snapshot.return_value = {'configured_tasks': []}
    with patch.object(main.AgentConfig, 'from_file', return_value=config), \
         patch.object(main, 'validate_model_credentials'), \
         patch.object(main.logging, 'FileHandler'), \
         patch.object(main.logging, 'basicConfig'), \
         patch.object(main, 'WhatsAppClient', return_value=client), \
         patch.object(main, '_wait_for_whatsapp'), \
         patch.object(main, '_run_bootstrap'), \
         patch.object(main, 'MCPManager', return_value=mcp), \
         patch.object(main, 'HeartbeatLoop', return_value=heartbeat), \
         patch.object(main.signal, 'signal'), \
         patch.object(main, 'run_poll_loop') as poll:
        main.main()
    client.send_message.assert_called_once()
    poll.assert_called_once()
    heartbeat.stop.assert_called_once()
    mcp.stop_all.assert_called_once()
    client.disconnect.assert_called_once()


def test_tool_audit_records_mcp_fetch_times_without_payloads(caplog):
    caplog.set_level(logging.INFO, logger='utils.tool_audit')
    hook = ToolAudit({'get_source_status': 'example-source'})
    hook.after_tool(SimpleNamespace(
        tool_use={'name': 'get_source_status', 'input': {'secret': 'PRIVATE_ARGUMENT'}},
        result={'status': 'success', 'content': [{'text': json.dumps({
            'retrieved_at': '2026-09-05T10:31:02+00:00',
            'private_report': 'PRIVATE_CONTENT'})}]},
    ))
    assert 'origin=example-source' in caplog.text and 'status=success' in caplog.text
    assert 'retrieved_at=2026-09-05T10:31:02' in caplog.text
    assert 'PRIVATE_ARGUMENT' not in caplog.text and 'PRIVATE_CONTENT' not in caplog.text


def test_tool_audit_records_tool_failure(caplog):
    caplog.set_level(logging.INFO, logger='utils.tool_audit')
    ToolAudit().after_tool(SimpleNamespace(tool_use={'name': 'reply'}, result={
        'status': 'success', 'content': [{'text': 'Failed to reply to PRIVATE_RECIPIENT'}]}))
    assert 'status=error' in caplog.text
    assert 'PRIVATE_RECIPIENT' not in caplog.text


def test_scheduler_context_requires_new_source_observations(tmp_path):
    (tmp_path / 'HEARTBEAT.md').write_text('- Monitor [every 1 min]: Check the source')
    loader = PersonaLoader(persona_dir=str(tmp_path))
    manager = MagicMock()
    loop = HeartbeatLoop(loader, manager, '111111111')
    from datetime import datetime, timezone
    loop._run_task(loader.load_heartbeat_tasks()[0], datetime.now(timezone.utc))
    prompt = manager.get_or_create.return_value.agent.call_args.args[0]
    assert 'call the relevant source tools during this execution' in prompt
    assert 'same source timestamp' in prompt
    assert loop.status_snapshot()['configured_tasks'][0]['interval_minutes'] == 1
    assert not loop.status_snapshot()['running']
