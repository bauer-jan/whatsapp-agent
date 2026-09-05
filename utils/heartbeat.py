"""Autonomous periodic task executor.

Runs heartbeat tasks defined in HEARTBEAT.md on their individual schedules
in a background thread. Uses the admin session via AgentManager so heartbeat
messages share conversation history with the admin DM.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from utils.persona_loader import HeartbeatTask, PersonaLoader

if TYPE_CHECKING:
    from utils.agent_manager import AgentManager

logger = logging.getLogger(__name__)

# How often the loop checks whether any task is due (seconds).
_TICK_INTERVAL = 10.0


class HeartbeatLoop:
    """Background loop that executes periodic heartbeat tasks."""

    def __init__(
        self,
        persona_loader: PersonaLoader,
        agent_manager: AgentManager,
        admin_phone: str,
        usage_callback: callable | None = None,
    ) -> None:
        self.persona_loader = persona_loader
        self.agent_manager = agent_manager
        self.admin_phone = admin_phone
        self.usage_callback = usage_callback
        self.tasks: list[HeartbeatTask] = []
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Load tasks from HEARTBEAT.md and begin the periodic loop."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Heartbeat thread is already running or still stopping")
        self._stop_event.clear()
        self.tasks = self.persona_loader.load_heartbeat_tasks()
        logger.info("Starting heartbeat loop with %d task(s)", len(self.tasks))
        for task in self.tasks:
            logger.info("Heartbeat scheduled: %s; first run in %d minute(s)",
                        task.name, task.interval_minutes)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the heartbeat loop gracefully."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=_TICK_INTERVAL + 2)
            if self._thread.is_alive():
                logger.warning(
                    "Heartbeat stop requested, but an active task is still running; "
                    "the thread did not finish within the shutdown timeout"
                )
                return
            self._thread = None
        logger.info("Heartbeat loop stopped")

    def status_snapshot(self) -> dict:
        """Report scheduler state and current file definitions, without running tasks."""
        return {
            "running": self._running,
            "configured_tasks": [
                {"name": task.name, "interval_minutes": task.interval_minutes}
                for task in self.persona_loader.load_heartbeat_tasks()
            ],
            "schedule_note": "Definitions reload every 10 seconds; tasks first run after their interval. "
                             "Active model calls and tool calls can delay execution.",
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main loop — reloads tasks from HEARTBEAT.md each tick, then runs
        any that are due."""
        while self._running:
            try:
                self._reload_tasks()
                now = datetime.now(timezone.utc)
                for task in self.tasks:
                    if not self._running:
                        break
                    if self._is_due(task, now):
                        self._run_task(task, now)
            except Exception:
                logger.exception("Heartbeat loop tick failed")
            self._stop_event.wait(_TICK_INTERVAL)

    def _reload_tasks(self) -> None:
        """Re-read HEARTBEAT.md and reconcile with the running task list.

        Existing tasks keep their ``last_run`` timestamp so they don't
        re-fire immediately after a reload.
        """
        try:
            fresh = self.persona_loader.load_heartbeat_tasks()
        except Exception:
            logger.exception("Failed to reload heartbeat tasks — keeping current list")
            return

        old_by_name = {t.name: t for t in self.tasks}
        merged: list[HeartbeatTask] = []
        for task in fresh:
            prev = old_by_name.get(task.name)
            if prev is not None:
                task.last_run = prev.last_run
            merged.append(task)

        added = {t.name for t in merged} - {t.name for t in self.tasks}
        removed = {t.name for t in self.tasks} - {t.name for t in merged}
        if added:
            logger.info("Heartbeat tasks added: %s", ", ".join(sorted(added)))
        if removed:
            logger.info("Heartbeat tasks removed: %s", ", ".join(sorted(removed)))

        self.tasks = merged

    @staticmethod
    def _is_due(task: HeartbeatTask, now: datetime) -> bool:
        """Return True if *task* should run based on its interval and last_run."""
        if task.last_run is None:
            task.last_run = now
            return False
        elapsed = (now - task.last_run).total_seconds()
        return elapsed >= task.interval_minutes * 60

    def _run_task(self, task: HeartbeatTask, now: datetime) -> None:
        """Execute a heartbeat task through the admin session.

        The agent decides whether to send a message via write_message tool.
        Text response is only logged, not auto-forwarded.
        """
        try:
            logger.info("▸ Heartbeat: %s", task.name)
            with self.agent_manager.session_lock(self.admin_phone):
                session = self.agent_manager.get_or_create(self.admin_phone, reply_to=self.admin_phone)

                session.agent(
                    f"[Heartbeat task — {task.name}]: {task.description}\n\n"
                    f"Scheduler execution time: {datetime.now(timezone.utc).isoformat()}. "
                    "This is a new execution. For current external "
                    "information, call the relevant source tools during this execution. Prior "
                    "conversation history is not a fresh observation. A new retrieval can return "
                    "the same source timestamp; report that honestly. Follow the task's conditions "
                    "for sending, and report unavailable sources instead of inventing updates."
                )

                usage = session.agent.event_loop_metrics.accumulated_usage
                if self.usage_callback:
                    self.usage_callback(usage)

                inp = usage.get("inputTokens", 0)
                out = usage.get("outputTokens", 0)
                tool_names = ",".join(session.agent.event_loop_metrics.tool_metrics.keys())
                logger.info("▸ Heartbeat done: %s  [%d→%d tok, tools: %s]",
                            task.name, inp, out, tool_names or "none (no message sent)")
                task.last_run = now

        except Exception:
            logger.exception("Heartbeat task failed: %s", task.name)
            task.last_run = now
