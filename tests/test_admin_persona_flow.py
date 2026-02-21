"""Tests for admin conversation → persona update flow.

Verifies that:
- Admin sessions receive USER.md in the system prompt
- Public sessions do NOT receive USER.md
- Persona update tools write to the correct files
- Updated files are picked up on subsequent session creation
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock neonize before importing anything that touches it.
_neonize_mock = MagicMock()
sys.modules.setdefault("neonize", _neonize_mock)
sys.modules.setdefault("neonize.client", _neonize_mock.client)
sys.modules.setdefault("neonize.events", _neonize_mock.events)
sys.modules.setdefault("neonize.utils", _neonize_mock.utils)
sys.modules.setdefault("neonize.utils.jid", _neonize_mock.utils.jid)

from tools.tool_manager import ToolManager
from tools.whatsapp_admin import (
    ALL_ADMIN_TOOLS,
    init as init_admin_tools,
    update_soul,
    update_user_profile,
    update_heartbeat,
)
from tools.whatsapp_public import ALL_PUBLIC_TOOLS
from utils.persona_loader import PersonaLoader
from utils.agent_manager import AgentManager


ADMIN_PHONE = "5511999999999"
PUBLIC_PHONE = "5522888888888"


def _make_agent_manager(persona_env):
    """Create an AgentManager from the persona_env fixture."""
    return AgentManager(
        storage_dir=str(persona_env["sessions_dir"]),
        persona_loader=persona_env["persona_loader"],
        tool_manager=persona_env["tool_manager"],
        wa_client=persona_env["wa_client"],
    )


@pytest.fixture
def persona_env(tmp_path):
    """Set up persona dir with templates and init admin tools."""
    templates_dir = tmp_path / "templates"
    persona_dir = tmp_path / "persona"
    sessions_dir = tmp_path / "sessions"
    templates_dir.mkdir()
    sessions_dir.mkdir()

    # Minimal templates.
    (templates_dir / "SOUL.md").write_text("You are a helpful agent.")
    (templates_dir / "USER.md").write_text("Admin user profile.")
    (templates_dir / "HEARTBEAT.md").write_text("# Heartbeat\n")
    (templates_dir / "BOOTSTRAP.md").write_text("# Bootstrap\n")

    persona_loader = PersonaLoader(
        templates_dir=str(templates_dir),
        persona_dir=str(persona_dir),
    )
    persona_loader.ensure_persona_files()

    tool_manager = ToolManager(admin_phone=ADMIN_PHONE)
    tool_manager.register_admin_tools(ALL_ADMIN_TOOLS)
    tool_manager.register_public_tools(ALL_PUBLIC_TOOLS)

    wa_client = MagicMock()
    wa_client.send_message.return_value = True
    init_admin_tools(wa_client=wa_client, persona_dir=str(persona_dir))

    return {
        "persona_loader": persona_loader,
        "tool_manager": tool_manager,
        "persona_dir": persona_dir,
        "sessions_dir": sessions_dir,
        "wa_client": wa_client,
    }


# ── Admin prompt injection ────────────────────────────────────────────


class TestAdminPromptInjection:
    """Admin sessions should include USER.md in the system prompt."""

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_admin_session_includes_user_profile(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)
        sm.get_or_create(ADMIN_PHONE)

        call_kwargs = mock_agent.call_args[1]
        assert "Admin user profile." in call_kwargs["system_prompt"]
        assert "helpful agent" in call_kwargs["system_prompt"]

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_public_session_excludes_user_profile(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)
        sm.get_or_create(PUBLIC_PHONE)

        call_kwargs = mock_agent.call_args[1]
        assert "Admin user profile." not in call_kwargs["system_prompt"]

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_admin_gets_admin_tools(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)
        sm.get_or_create(ADMIN_PHONE)

        call_kwargs = mock_agent.call_args[1]
        tool_names = {t.tool_name for t in call_kwargs["tools"]}
        assert "update_soul" in tool_names
        assert "update_user_profile" in tool_names
        assert "update_heartbeat" in tool_names

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_public_lacks_admin_tools(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)
        sm.get_or_create(PUBLIC_PHONE)

        call_kwargs = mock_agent.call_args[1]
        tool_names = {t.tool_name for t in call_kwargs["tools"]}
        assert "update_soul" not in tool_names


# ── Persona update tools write correctly ─────────────────────────────


class TestPersonaUpdates:
    """Tools write to the correct files and changes are picked up."""

    def test_update_user_profile_writes_file(self, persona_env):
        result = update_user_profile(content="# User\n\nName: Jan\nTimezone: CET")
        assert "Updated" in result
        assert "Jan" in (persona_env["persona_dir"] / "USER.md").read_text()

    def test_update_soul_writes_file(self, persona_env):
        result = update_soul(content="# Soul\n\nI am friendly and casual.")
        assert "Updated" in result
        assert "friendly" in (persona_env["persona_dir"] / "SOUL.md").read_text()

    def test_update_heartbeat_writes_file(self, persona_env):
        content = "# Heartbeat\n\n- Check In [every 60 min]: Say hi"
        result = update_heartbeat(content=content)
        assert "Updated" in result
        assert "[every 60 min]" in (persona_env["persona_dir"] / "HEARTBEAT.md").read_text()


# ── Round-trip: update then reload ───────────────────────────────────


class TestPersonaRoundTrip:
    """Updated persona files are picked up on the next session creation."""

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_soul_update_reflected_in_next_session(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)

        # Update soul.
        update_soul(content="# Soul\n\nI am sarcastic and witty.")

        sm.get_or_create(ADMIN_PHONE)
        prompt = mock_agent.call_args[1]["system_prompt"]
        assert "sarcastic" in prompt
        assert "helpful agent" not in prompt

    @patch("utils.agent_manager.make_reply_tool", return_value=MagicMock(tool_name="reply"))
    @patch("utils.agent_manager.Agent")
    @patch("utils.agent_manager.FileSessionManager")
    @patch("utils.agent_manager.SummarizingConversationManager")
    def test_user_profile_update_reflected_in_next_session(self, _conv, _fsm, mock_agent, _reply, persona_env):
        sm = _make_agent_manager(persona_env)

        update_user_profile(content="# User\n\nName: Jan\nLikes: coffee, cycling")

        sm.get_or_create(ADMIN_PHONE)
        prompt = mock_agent.call_args[1]["system_prompt"]
        assert "Jan" in prompt
        assert "cycling" in prompt

    def test_heartbeat_update_reflected_in_loader(self, persona_env):
        update_heartbeat(
            content="# Heartbeat\n\n- Daily Summary [every 1440 min]: Summarize the day"
        )
        tasks = persona_env["persona_loader"].load_heartbeat_tasks()
        assert len(tasks) == 1
        assert tasks[0].name == "Daily Summary"
        assert tasks[0].interval_minutes == 1440
