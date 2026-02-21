"""Property and unit tests for SessionManager (Tasks 3.2, 3.3).

SessionManager depends on Strands Agent, PersonaLoader, and ToolManager.
We mock those to test the pure session-management logic: idempotence,
isolation, and phone normalization.
"""

from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.agent_manager import AgentManager, normalize_phone


phone_st = st.from_regex(r"[1-9]\d{7,14}", fullmatch=True)


def _make_session_manager() -> AgentManager:
    """Create a SessionManager with mocked dependencies."""
    persona_loader = MagicMock()
    persona_loader.load_public_prompt.return_value = "You are a helpful agent."

    tool_manager = MagicMock()
    tool_manager.get_role.return_value = "public"
    tool_manager.get_tools.return_value = []

    sm = AgentManager(
        storage_dir="/tmp/test_sessions",
        persona_loader=persona_loader,
        tool_manager=tool_manager,
        wa_client=MagicMock(),
    )
    return sm


# ---------------------------------------------------------------------------
# Property 2: Session get_or_create is idempotent for existing sessions
# Feature: whatsapp-agent, Property 2: Session get_or_create is idempotent
# ---------------------------------------------------------------------------

@given(phone=phone_st)
@settings(max_examples=100)
@patch("utils.agent_manager.make_reply_tool", return_value=MagicMock())
@patch("utils.agent_manager.Agent")
@patch("utils.agent_manager.FileSessionManager")
@patch("utils.agent_manager.SummarizingConversationManager")
def test_property_get_or_create_idempotent(mock_conv, mock_fsm, mock_agent, _reply, phone):
    """Calling get_or_create twice returns the same session_id."""
    sm = _make_session_manager()
    s1 = sm.get_or_create(phone)
    s2 = sm.get_or_create(phone)
    assert s1.session_id == s2.session_id
    assert s1 is s2 or s1.session_id == s2.session_id


# ---------------------------------------------------------------------------
# Property 3: Session isolation — no two phones share a session_id
# Feature: whatsapp-agent, Property 3: Session isolation
# ---------------------------------------------------------------------------

@given(
    phone_a=phone_st,
    phone_b=phone_st,
)
@settings(max_examples=100)
@patch("utils.agent_manager.make_reply_tool", return_value=MagicMock())
@patch("utils.agent_manager.Agent")
@patch("utils.agent_manager.FileSessionManager")
@patch("utils.agent_manager.SummarizingConversationManager")
def test_property_session_isolation(mock_conv, mock_fsm, mock_agent, _reply, phone_a, phone_b):
    """Distinct phone numbers get distinct session_ids (unless they normalize to the same digits)."""
    sm = _make_session_manager()
    sa = sm.get_or_create(phone_a)
    sb = sm.get_or_create(phone_b)
    if normalize_phone(phone_a) != normalize_phone(phone_b):
        assert sa.session_id != sb.session_id


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_strips_non_digits(self):
        assert normalize_phone("+1 (555) 123-4567") == "15551234567"

    def test_pure_digits_unchanged(self):
        assert normalize_phone("5511999999999") == "5511999999999"
