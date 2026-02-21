"""Permission-based tool injection — Admin vs Public tool sets."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SenderRole(str, Enum):
    """Role assigned to a message sender based on phone identity."""

    ADMIN = "admin"
    PUBLIC = "public"


class ToolManager:
    """Determines which tool set a sender receives based on phone identity.

    Usage::

        tm = ToolManager(admin_phone="5511999999999")
        role = tm.get_role(sender_phone)
        tools = tm.get_tools(role)
    """

    def __init__(self, admin_phone: str) -> None:
        self.admin_phone = admin_phone
        self._admin_tools: list[Any] = []
        self._public_tools: list[Any] = []

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_admin_tools(self, tools: list[Any]) -> None:
        """Register the full set of admin-only tool functions."""
        self._admin_tools = list(tools)

    def register_public_tools(self, tools: list[Any]) -> None:
        """Register the restricted public tool functions."""
        self._public_tools = list(tools)


    # ------------------------------------------------------------------
    # Role resolution
    # ------------------------------------------------------------------

    def get_role(self, phone: str | None) -> SenderRole:
        """Return ADMIN iff *phone* matches the configured admin phone.

        Defaults to PUBLIC for None, empty string, or any non-matching number.
        """
        if not phone:
            return SenderRole.PUBLIC
        return SenderRole.ADMIN if phone == self.admin_phone else SenderRole.PUBLIC

    # ------------------------------------------------------------------
    # Tool injection
    # ------------------------------------------------------------------

    def get_tools(self, role: SenderRole) -> list[Any]:
        """Return the tool list appropriate for *role*.

        ADMIN receives the full tool set (admin + public).
        PUBLIC receives only the restricted set.
        """
        if role is SenderRole.ADMIN:
            return self._admin_tools + self._public_tools
        return list(self._public_tools)
