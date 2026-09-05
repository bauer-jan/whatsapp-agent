"""Public Strands @tool functions available to all WhatsApp users."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from strands import tool

if TYPE_CHECKING:
    from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)


def make_reply_tool(wa_client: WhatsAppClient, reply_to: str):
    """Create a reply tool with the chat target baked in via closure."""

    @tool
    def reply(message: str) -> str:
        """Reply to the sender who initiated this turn.

        Reading another contact's messages does not change this destination.
        Use write_message to send to a different person or group (admin only).

        Args:
            message: Text message to send.
        """
        ok = wa_client.send_message(reply_to, message)
        if ok:
            return f"Replied to {reply_to}"
        return f"Failed to reply to {reply_to}"

    return reply


@tool
def read_message() -> str:
    """Read the current conversation context.

    Returns a confirmation that the agent has access to the conversation.
    The actual conversation history is managed by the Strands session.
    """
    return "I have access to our conversation context. How can I help you?"


ALL_PUBLIC_TOOLS = [read_message]
