"""Agent tools — permission-based tool sets."""

from tools.tool_manager import ToolManager, SenderRole
from tools.whatsapp_admin import (
    ALL_ADMIN_TOOLS,
    init as init_admin_tools,
    update_soul,
    update_user_profile,
    update_heartbeat,
    set_heartbeat_task,
    remove_heartbeat_task,
    lookup_contact,
    read_recent_messages,
    write_message,
)
from tools.whatsapp_public import ALL_PUBLIC_TOOLS

__all__ = [
    "ALL_ADMIN_TOOLS",
    "ALL_PUBLIC_TOOLS",
    "SenderRole",
    "ToolManager",
    "init_admin_tools",
    "lookup_contact",
    "read_recent_messages",
    "update_heartbeat",
    "set_heartbeat_task",
    "remove_heartbeat_task",
    "update_soul",
    "update_user_profile",
    "write_message",
]
