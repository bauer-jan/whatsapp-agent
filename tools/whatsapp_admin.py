"""Admin-only Strands @tool functions for WhatsApp agent.

These tools are injected only when the sender is the Admin.
Module-level references are set by ``init()`` at startup.
"""

from __future__ import annotations

import logging
import re
import json
import os
import tempfile
import unicodedata
import threading
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
    """Send a WhatsApp message to a specific phone number or group.

    Use this to fulfill the admin's request to send or reply to another contact.
    Resolve the recipient using lookup_contact. The reply tool sends to the
    admin instead; it cannot deliver a reply to the contact on the admin's behalf.

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
    in_rules = False
    task_pattern = re.compile(r"^-\s+.+?\s+\[every\s+[1-9]\d*\s+min\]\s*:\s*\S.*$")
    count = 0
    for line in content.splitlines():
        if line.startswith("## "):
            in_rules = line[3:].strip().casefold() == "rules"
        candidate = line.strip()
        if candidate.startswith("-") and (not in_rules or "[every" in candidate):
            if not task_pattern.fullmatch(line):
                return "Error: task lines must use '- Task Name [every N min]: Description', with N >= 1. File unchanged."
            count += 1
    if count == 0 and any(line.strip() and not line.startswith("#") for line in content.splitlines()):
        return "Error: no valid tasks found. Use '- Task Name [every N min]: Description' or an empty file to clear tasks. File unchanged."
    result = _write_persona_file("HEARTBEAT.md", content)
    return f"{result}; {count} task(s) configured. First run is after each task's interval while James is running."


_heartbeat_edit_lock = threading.RLock()
_TASK_LINE = re.compile(r"^-\s+(.+?)\s+\[every\s+(\d+)\s+min\]\s*:\s*(.+)$")


@tool
def set_heartbeat_task(name: str, interval_minutes: int, description: str) -> str:
    """Add or change one recurring task, preserving every other task and rule on disk.

    Use only for a task explicitly requested by the admin. Do not copy tasks
    from conversation history. Confirm scheduling only after this tool succeeds.

    Args:
        name: A short unique task name. Reuse the exact name when changing it.
        interval_minutes: Positive integer interval in minutes.
        description: Instructions for this task, on one line.
    """
    if type(interval_minutes) is not int or interval_minutes < 1:
        return "Error: interval_minutes must be a positive integer"
    name = name.strip()
    description = description.strip()
    if (not name or not description or any(c in name for c in "\r\n[]")
            or any(c in description for c in "\r\n")):
        return "Error: provide a single-line task name and description; name cannot contain brackets"
    with _heartbeat_edit_lock:
        path = _persona_dir / "HEARTBEAT.md"
        lines = path.read_text().splitlines() if path.exists() else []
        updated = []
        replaced = False
        task_line = f"- {name} [every {interval_minutes} min]: {description}"
        for line in lines:
            match = _TASK_LINE.fullmatch(line)
            if match and match.group(1).strip().casefold() == name.casefold():
                if not replaced:
                    updated.append(task_line)
                    replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated = [task_line, ""] + updated
        _write_persona_file("HEARTBEAT.md", "\n".join(updated) + "\n")
        return f"Saved task '{name}' every {interval_minutes} minute(s). Other tasks preserved. First run is after the interval."


@tool
def remove_heartbeat_task(name: str) -> str:
    """Remove exactly one named recurring task while preserving all others.

    Use get_runtime_status to look up the exact current task name if needed.

    Args:
        name: Exact task name to remove (case insensitive).
    """
    with _heartbeat_edit_lock:
        path = _persona_dir / "HEARTBEAT.md"
        lines = path.read_text().splitlines() if path.exists() else []
        updated = []
        removed = False
        for line in lines:
            match = _TASK_LINE.fullmatch(line)
            if match and match.group(1).strip().casefold() == name.strip().casefold():
                removed = True
            else:
                updated.append(line)
        if not removed:
            return "Task not found. No changes made; inspect get_runtime_status for current task names."
        _write_persona_file("HEARTBEAT.md", "\n".join(updated) + "\n")
        return f"Removed task '{name}'. Other tasks preserved."


_ALLOWED_PERSONA_FILES = {"SOUL.md", "USER.md", "HEARTBEAT.md"}


def _write_persona_file(file_name: str, content: str) -> str:
    """Write content to a persona file. Internal helper."""
    if file_name not in _ALLOWED_PERSONA_FILES:
        return f"Error: '{file_name}' is not a valid persona file"
    target = _persona_dir / file_name
    # Resolve to catch any path traversal attempts
    if target.resolve().parent != _persona_dir.resolve():
        return f"Error: invalid file path for {file_name}"
    _persona_dir.mkdir(parents=True, exist_ok=True)
    # The scheduler may read concurrently: publish a complete file atomically.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=_persona_dir, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
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
        def folded(value: str) -> str:
            return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                                    if not unicodedata.combining(c)).split())

        query_lower = folded(query)
        if not query_lower:
            return "Error: provide a contact name or phone number"
        query_words = query_lower.split()
        suggestions = {}
        contact_results = {}
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
                if hasattr(jid, "User"):
                    phone = _wa_client._phone_for_jid(jid) or f"{jid.User}@{jid.Server}"
                else:
                    phone = str(jid)

            name_match = any(query_lower in folded(n) for n in names)
            partial_match = len(query_words) > 1 and any(
                query_words[0] in folded(n).split() for n in names
            )
            phone_match = bool(query_digits and phone and query_digits in phone)

            if phone and (name_match or phone_match or partial_match):
                display_name = names[0] if names else "(no name)"
                entry = f"{display_name} — {phone}"
                if name_match or phone_match:
                    contact_results[phone] = entry
                else:
                    suggestions[phone] = entry

        results.extend(contact_results.values())

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

        if not results and suggestions:
            return ("No exact full-name match. Possible first-name matches follow. "
                    "Ask the admin to confirm the intended person before sending:\n"
                    + "\n".join(list(suggestions.values())[:20]))
        if not results:
            return f"No contacts or groups found matching '{query}' (searched {len(contacts)} contacts)"
        prefix = "Multiple matches: ask the admin which recipient they mean before sending.\n" if len(results) > 1 else ""
        return prefix + "\n".join(results[:20])
    except Exception as e:
        return f"Error looking up contact: {e}"


@tool
def read_recent_messages(phone: str, limit: int = 10) -> str:
    """Read recent text messages in a resolved contact's chat (admin only).

    Includes messages blocked from automatic replies. Only text events received
    since James started are available, from a buffer of at most 1000 events.
    Resolve names with lookup_contact first. Missing history must not be invented.

    Args:
        phone: Resolved recipient phone number or complete chat JID.
        limit: Number of recent messages to read, from 1 to 20.
    """
    if _wa_client is None:
        return "Error: WhatsApp client not initialized"
    if not 1 <= limit <= 20:
        return "Error: limit must be between 1 and 20"
    messages = _wa_client.get_recent_messages(phone, limit)
    if not messages:
        return "No recent text messages available for this chat since startup. Ask the admin to provide the message to answer."
    return json.dumps({
        "chat_id": phone,
        "scope": "Recent text events received since startup; not full WhatsApp history",
        "messages": [{"text": m.body, "from_me": m.is_from_me, "timestamp": m.timestamp}
                     for m in messages],
        "reply_delivery": "To answer this contact, call write_message with this chat_id. "
                          "The reply tool still sends to the admin's conversation.",
    }, ensure_ascii=False)


# Convenience list for ToolManager registration.
ALL_ADMIN_TOOLS = [
    write_message,
    update_soul, update_user_profile, set_heartbeat_task, remove_heartbeat_task,
    lookup_contact, read_recent_messages,
]
