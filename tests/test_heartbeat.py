"""Unit tests for HeartbeatLoop."""

import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


# Mock neonize before importing heartbeat (which imports whatsapp_client)
_neonize_mock = MagicMock()
sys.modules.setdefault("neonize", _neonize_mock)
sys.modules.setdefault("neonize.client", _neonize_mock.client)
sys.modules.setdefault("neonize.events", _neonize_mock.events)
sys.modules.setdefault("neonize.utils", _neonize_mock.utils)
sys.modules.setdefault("neonize.utils.jid", _neonize_mock.utils.jid)

from utils.persona_loader import HeartbeatTask
from utils.heartbeat import HeartbeatLoop


def _make_heartbeat_loop(tasks=None):
    """Create a HeartbeatLoop with mocked dependencies."""
    persona_loader = MagicMock()
    persona_loader.load_heartbeat_tasks.return_value = tasks or []

    agent_manager = MagicMock()

    loop = HeartbeatLoop(
        persona_loader=persona_loader,
        agent_manager=agent_manager,
        admin_phone="5511999999999",
    )
    return loop


class TestIsDue:
    def test_never_run_not_due_sets_last_run(self):
        task = HeartbeatTask(name="t", description="d", interval_minutes=60, last_run=None)
        now = datetime.now(timezone.utc)
        assert HeartbeatLoop._is_due(task, now) is False
        assert task.last_run == now

    def test_recently_run_not_due(self):
        now = datetime.now(timezone.utc)
        task = HeartbeatTask(
            name="t", description="d", interval_minutes=60,
            last_run=now - timedelta(minutes=10),
        )
        assert HeartbeatLoop._is_due(task, now) is False

    def test_past_interval_is_due(self):
        now = datetime.now(timezone.utc)
        task = HeartbeatTask(
            name="t", description="d", interval_minutes=60,
            last_run=now - timedelta(minutes=61),
        )
        assert HeartbeatLoop._is_due(task, now) is True

    def test_exactly_at_interval_is_due(self):
        now = datetime.now(timezone.utc)
        task = HeartbeatTask(
            name="t", description="d", interval_minutes=30,
            last_run=now - timedelta(minutes=30),
        )
        assert HeartbeatLoop._is_due(task, now) is True


class TestRunTask:
    def test_uses_admin_session_and_sends_response(self):
        usage_cb = MagicMock()
        loop = _make_heartbeat_loop()
        loop.usage_callback = usage_cb

        mock_session = MagicMock()
        mock_session.agent.return_value = "Here's a joke for you"
        mock_session.agent.event_loop_metrics.accumulated_usage = {
            "inputTokens": 10, "outputTokens": 5, "totalTokens": 15,
        }
        loop.agent_manager.get_or_create.return_value = mock_session

        task = HeartbeatTask(name="Check In", description="Status update", interval_minutes=60)
        now = datetime.now(timezone.utc)

        loop._run_task(task, now)

        loop.agent_manager.get_or_create.assert_called_once_with("5511999999999", reply_to="5511999999999")
        mock_session.agent.assert_called_once()
        usage_cb.assert_called_once_with({"inputTokens": 10, "outputTokens": 5, "totalTokens": 15})
        assert task.last_run == now

    def test_failure_logs_and_marks_run(self):
        loop = _make_heartbeat_loop()
        loop.agent_manager.get_or_create.side_effect = RuntimeError("agent failed")

        task = HeartbeatTask(name="Broken", description="Will fail", interval_minutes=60)
        now = datetime.now(timezone.utc)

        loop._run_task(task, now)
        assert task.last_run == now


class TestReloadTasks:
    def test_preserves_last_run_on_reload(self):
        old_task = HeartbeatTask(
            name="Check In", description="old", interval_minutes=60,
            last_run=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        loop = _make_heartbeat_loop(tasks=[old_task])
        loop.tasks = [old_task]

        new_task = HeartbeatTask(name="Check In", description="updated", interval_minutes=30)
        loop.persona_loader.load_heartbeat_tasks.return_value = [new_task]

        loop._reload_tasks()

        assert len(loop.tasks) == 1
        assert loop.tasks[0].description == "updated"
        assert loop.tasks[0].interval_minutes == 30
        # last_run preserved from old task
        assert loop.tasks[0].last_run == datetime(2025, 1, 1, tzinfo=timezone.utc)

    def test_adds_new_tasks(self):
        loop = _make_heartbeat_loop()
        loop.tasks = []

        new_task = HeartbeatTask(name="New", description="fresh", interval_minutes=10)
        loop.persona_loader.load_heartbeat_tasks.return_value = [new_task]

        loop._reload_tasks()
        assert len(loop.tasks) == 1
        assert loop.tasks[0].name == "New"

    def test_removes_deleted_tasks(self):
        old = HeartbeatTask(name="Old", description="gone", interval_minutes=60)
        loop = _make_heartbeat_loop()
        loop.tasks = [old]
        loop.persona_loader.load_heartbeat_tasks.return_value = []

        loop._reload_tasks()
        assert len(loop.tasks) == 0
