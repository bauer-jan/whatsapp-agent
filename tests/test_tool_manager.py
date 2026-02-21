"""Property and unit tests for ToolManager (Task 4.2).

Tests role resolution and tool injection based on phone identity.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from tools.tool_manager import ToolManager, SenderRole


phone_st = st.from_regex(r"[1-9]\d{7,14}", fullmatch=True)
admin_phone_st = st.from_regex(r"[1-9]\d{7,14}", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 4: Role-based tool injection follows phone identity
# Feature: whatsapp-agent, Property 4: Role-based tool injection
# ---------------------------------------------------------------------------

@given(admin_phone=admin_phone_st, sender_phone=phone_st)
@settings(max_examples=100)
def test_property_role_follows_identity(admin_phone, sender_phone):
    """get_role returns ADMIN iff sender == admin_phone."""
    tm = ToolManager(admin_phone=admin_phone)
    role = tm.get_role(sender_phone)
    if sender_phone == admin_phone:
        assert role is SenderRole.ADMIN
    else:
        assert role is SenderRole.PUBLIC


@given(admin_phone=admin_phone_st)
@settings(max_examples=100)
def test_property_admin_gets_superset_of_public(admin_phone):
    """Admin tool set is always a superset of the public tool set."""
    tm = ToolManager(admin_phone=admin_phone)
    # Register some dummy tools
    admin_tools = [lambda: "admin1", lambda: "admin2"]
    public_tools = [lambda: "public1"]
    tm.register_admin_tools(admin_tools)
    tm.register_public_tools(public_tools)

    admin_result = tm.get_tools(SenderRole.ADMIN)
    public_result = tm.get_tools(SenderRole.PUBLIC)

    # Admin gets admin + public tools
    assert len(admin_result) == len(admin_tools) + len(public_tools)
    # Public gets only public tools
    assert len(public_result) == len(public_tools)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestToolManagerEdgeCases:
    def test_none_phone_returns_public(self):
        tm = ToolManager(admin_phone="123")
        assert tm.get_role(None) is SenderRole.PUBLIC

    def test_empty_phone_returns_public(self):
        tm = ToolManager(admin_phone="123")
        assert tm.get_role("") is SenderRole.PUBLIC

    def test_admin_phone_returns_admin(self):
        tm = ToolManager(admin_phone="5511999999999")
        assert tm.get_role("5511999999999") is SenderRole.ADMIN

    def test_different_phone_returns_public(self):
        tm = ToolManager(admin_phone="5511999999999")
        assert tm.get_role("5511888888888") is SenderRole.PUBLIC

    def test_empty_tools_by_default(self):
        tm = ToolManager(admin_phone="123")
        assert tm.get_tools(SenderRole.ADMIN) == []
        assert tm.get_tools(SenderRole.PUBLIC) == []
