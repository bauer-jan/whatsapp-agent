"""Persona file loading, prompt assembly, and heartbeat task parsing."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PERSONA_FILES = ("SOUL.md", "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md")


@dataclass
class HeartbeatTask:
    """A single periodic task parsed from HEARTBEAT.md."""

    name: str
    description: str
    interval_minutes: int
    last_run: datetime | None = None


class PersonaLoader:
    """Loads persona files from disk and assembles prompts.

    On startup, copies missing persona files from templates/ so the agent
    always has a complete set. Existing persona/ files are never overwritten.
    """

    def __init__(
        self,
        templates_dir: str = "templates/",
        persona_dir: str = "persona/",
        admin_phone: str = "",
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.persona_dir = Path(persona_dir)
        self.admin_phone = admin_phone

    def ensure_persona_files(self) -> None:
        """Copy missing persona files from templates/ to persona/.

        For each expected file, if it already exists in persona/ it is left
        unchanged. If it is missing from both persona/ and templates/, a
        warning is logged and the file is skipped.
        """
        self.persona_dir.mkdir(parents=True, exist_ok=True)

        for filename in PERSONA_FILES:
            dest = self.persona_dir / filename
            if dest.exists():
                continue

            src = self.templates_dir / filename
            if not src.exists():
                logger.warning("Template missing for %s — skipping", filename)
                continue

            shutil.copy2(src, dest)
            logger.info("Copied template %s → %s", src, dest)

    def load_public_prompt(self) -> str:
        """Assemble the base system prompt from SOUL.md + runtime context.

        This is the public-facing prompt. Admin/system sessions should use
        load_admin_prompt() instead.
        """
        parts: list[str] = []
        soul = self.persona_dir / "SOUL.md"
        if soul.exists():
            parts.append(soul.read_text())
        else:
            logger.warning("SOUL.md not found — skipping")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"## System Context\n\nCurrent time: {now}")

        return "\n\n".join(parts)

    def load_admin_prompt(self) -> str:
        """Assemble the full prompt for admin and system sessions.

        Includes SOUL.md + USER.md + HEARTBEAT.md + admin context + system context.
        """
        parts: list[str] = []

        for filename in ("SOUL.md", "USER.md", "HEARTBEAT.md"):
            path = self.persona_dir / filename
            if path.exists():
                parts.append(path.read_text())

        if self.admin_phone:
            parts.append(f"Admin phone: {self.admin_phone}")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"## System Context\n\nCurrent time: {now}")

        return "\n\n".join(parts)

    def load_bootstrap(self) -> str:
        """Load the BOOTSTRAP.md initialization sequence."""
        path = self.persona_dir / "BOOTSTRAP.md"
        if not path.exists():
            logger.warning("BOOTSTRAP.md not found in %s", self.persona_dir)
            return ""
        return path.read_text()

    def load_heartbeat_tasks(self) -> list[HeartbeatTask]:
        """Parse HEARTBEAT.md into a list of HeartbeatTask objects.

        Expected format per task line::

            - Task Name [every N min]: Description text here

        Lines that don't match the pattern are silently skipped.
        """
        path = self.persona_dir / "HEARTBEAT.md"
        if not path.exists():
            logger.warning("HEARTBEAT.md not found in %s", self.persona_dir)
            return []

        content = path.read_text()
        pattern = re.compile(
            r"^-\s+(.+?)\s+\[every\s+(\d+)\s+min\]\s*:\s*(.+)$",
            re.MULTILINE,
        )

        tasks: list[HeartbeatTask] = []
        for match in pattern.finditer(content):
            name = match.group(1).strip()
            interval = max(int(match.group(2)), 1)  # Minimum 1 min
            description = match.group(3).strip()
            tasks.append(HeartbeatTask(name=name, description=description, interval_minutes=interval))

        return tasks
