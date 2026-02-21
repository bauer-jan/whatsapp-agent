"""Admin-only Strands @tool functions for WhatsApp agent.

These tools are injected only when the sender is the Admin.
Module-level references are set by ``init()`` at startup.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from strands import tool

if TYPE_CHECKING:
    from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

# Module-level references — set via init() before tools are used.
_wa_client: WhatsAppClient | None = None
_persona_dir: Path = Path("persona/")


def init(
    wa_client: WhatsAppClient,
    persona_dir: str = "persona/",
) -> None:
    """Bind shared state so tools can access the WhatsApp client."""
    global _wa_client, _persona_dir
    _wa_client = wa_client
    _persona_dir = Path(persona_dir)


@tool
def write_message(phone: str, message: str) -> str:
    """Send a WhatsApp message to any phone number or group.

    Args:
        phone: Recipient phone number or group chat_id.
        message: Text message to send.
    """
    if _wa_client is None:
        return "Error: WhatsApp client not initialized"
    ok = _wa_client.send_message(phone, message)
    if ok:
        return f"Message sent to {phone}"
    return f"Failed to send message to {phone}"


@tool
def update_soul(content: str) -> str:
    """Rewrite your personality and behavior rules (SOUL.md).

    Call this when the admin asks you to change how you behave, your name,
    communication style, or boundaries. Tell the admin before changing this.

    Args:
        content: Complete updated SOUL.md content (replaces the file).
    """
    return _write_persona_file("SOUL.md", content)


@tool
def update_user_profile(content: str) -> str:
    """Update what you know about the admin (USER.md).

    Call this when you learn new facts about the admin — their name, timezone,
    preferences, work context, or anything personal they share.

    Args:
        content: Complete updated USER.md content (replaces the file).
    """
    return _write_persona_file("USER.md", content)


@tool
def update_heartbeat(content: str) -> str:
    """Update your periodic background tasks (HEARTBEAT.md).

    Call this when the admin asks you to add, remove, or change recurring tasks.
    Each task line MUST follow: `- Task Name [every N min]: Description`

    Args:
        content: Complete updated HEARTBEAT.md content (replaces the file).
    """
    return _write_persona_file("HEARTBEAT.md", content)


_ALLOWED_PERSONA_FILES = {"SOUL.md", "USER.md", "HEARTBEAT.md"}


def _write_persona_file(file_name: str, content: str) -> str:
    """Write content to a persona file. Internal helper."""
    if file_name not in _ALLOWED_PERSONA_FILES:
        return f"Error: '{file_name}' is not a valid persona file"
    target = _persona_dir / file_name
    # Resolve to catch any path traversal attempts
    if target.resolve().parent != _persona_dir.resolve():
        return f"Error: invalid file path for {file_name}"
    target.write_text(content)
    return f"Updated {file_name}"


@tool
def lookup_contact(query: str) -> str:
    """Look up a WhatsApp contact or group by name or phone number.

    Call this IMMEDIATELY when the user mentions a person's name — don't ask
    for their number first. Searches contacts and joined groups for partial
    case-insensitive matches.

    Args:
        query: Name or phone number to search for (case-insensitive partial match).
    """
    if _wa_client is None:
        return "Error: WhatsApp client not initialized"
    try:
        query_lower = query.lower().strip()
        query_digits = re.sub(r"\D", "", query)
        results = []

        # Search contacts.
        contacts = _wa_client.client.contact.get_all_contacts()
        for c in contacts:
            info = getattr(c, "Info", None)
            names: list[str] = []
            if info:
                for attr in ("FullName", "PushName", "FirstName", "BusinessName"):
                    val = getattr(info, attr, None)
                    if val:
                        names.append(str(val))
            if not names:
                for attr in ("FullName", "PushName", "FirstName", "BusinessName"):
                    val = getattr(c, attr, None)
                    if val:
                        names.append(str(val))

            phone = ""
            jid = getattr(c, "JID", None)
            if jid:
                phone = str(jid.User) if hasattr(jid, "User") else str(jid)

            name_match = any(query_lower in n.lower() for n in names)
            phone_match = bool(query_digits and phone and query_digits in phone)

            if name_match or phone_match:
                display_name = names[0] if names else "(no name)"
                results.append(f"{display_name} — {phone}")

        # Search groups.
        try:
            groups = _wa_client.client.get_joined_groups()
            for g in groups:
                group_name = ""
                gn = getattr(g, "GroupName", None)
                if gn:
                    group_name = getattr(gn, "Name", "") or ""
                group_jid = ""
                jid = getattr(g, "JID", None)
                if jid:
                    group_jid = f"{jid.User}@{jid.Server}" if hasattr(jid, "User") else str(jid)

                if group_name and query_lower in group_name.lower():
                    results.append(f"[Group] {group_name} — {group_jid}")
        except Exception:
            logger.debug("Could not search groups", exc_info=True)

        if not results:
            return f"No contacts or groups found matching '{query}' (searched {len(contacts)} contacts)"
        return "\n".join(results[:20])
    except Exception as e:
        return f"Error looking up contact: {e}"


# Convenience list for ToolManager registration.
ALL_ADMIN_TOOLS = [
    write_message,
    update_soul, update_user_profile, update_heartbeat,
    lookup_contact,
]
