"""Per-phone session isolation with Strands FileSessionManager."""

from __future__ import annotations

import logging
import json
from collections.abc import Callable
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from strands import Agent
from strands.agent.conversation_manager.summarizing_conversation_manager import SummarizingConversationManager
from strands.session.file_session_manager import FileSessionManager

if TYPE_CHECKING:
    from utils.persona_loader import PersonaLoader
    from tools.tool_manager import ToolManager
    from utils.whatsapp_client import WhatsAppClient

from utils.config import ModelConfig
from utils.model_factory import create_model
from tools.tool_manager import SenderRole
from tools.whatsapp_public import make_reply_tool
from tools.runtime_status import make_runtime_status_tool
from utils.tool_audit import ToolAudit
from utils.whatsapp_client import normalize_phone

logger = logging.getLogger(__name__)


@dataclass
class AgentSession:
    """An isolated agent session bound to a single phone number."""

    phone: str
    session_id: str
    agent: Agent
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentManager:
    """Creates a fresh Strands agent per message.

    Conversation history is persisted to disk via FileSessionManager,
    so each new Agent instance loads prior context automatically.
    No in-memory session cache needed.
    """

    def __init__(
        self,
        storage_dir: str,
        persona_loader: PersonaLoader,
        tool_manager: ToolManager,
        wa_client: WhatsAppClient,
        model_config: ModelConfig | None = None,
        runtime_context_provider: Callable[[], dict] | None = None,
    ) -> None:
        self.storage_dir = storage_dir
        self.persona_loader = persona_loader
        self.tool_manager = tool_manager
        self.wa_client = wa_client
        self.model_config = model_config
        self.runtime_context_provider = runtime_context_provider
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def session_lock(self, phone: str):
        """Serialize history load, invocation and writes for the same session."""
        with self._locks_guard:
            return self._locks.setdefault(normalize_phone(phone), threading.RLock())

    def get_or_create(self, phone: str, reply_to: str | None = None) -> AgentSession:
        """Create a fresh agent for this phone number.

        Args:
            phone: The sender's phone number (used for session ID and role).
            reply_to: Chat ID to bake into the reply tool. Defaults to phone.
        """
        normalized = normalize_phone(phone)
        session_id = f"wa_{normalized}"
        target = reply_to or normalized

        role = self.tool_manager.get_role(normalized)
        tools = self.tool_manager.get_tools(role)

        # Create a reply tool with the chat target baked in
        reply_tool = make_reply_tool(self.wa_client, target)
        tools = tools + [reply_tool]

        origins = {}
        if role is SenderRole.ADMIN:
            def runtime_snapshot():
                snapshot = dict(self.runtime_context_provider()) if self.runtime_context_provider else {
                    "mcp_inventory_available": False,
                    "mcp_servers": [],
                }
                snapshot["available_tools"] = sorted({
                    tool.tool_name for tool in tools if isinstance(getattr(tool, "tool_name", None), str)})
                if self.model_config is not None:
                    snapshot["model"] = {"provider": self.model_config.provider,
                                         "model_id": self.model_config.model_id}
                snapshot["inventory_scope"] = (
                    "Registered capabilities for this admin turn. MCP status describes startup "
                    "and discovery, not a continuous reachability check. Query source tools for current data.")
                return snapshot

            tools = tools + [make_runtime_status_tool(runtime_snapshot)]
            snapshot = runtime_snapshot()
            for server in snapshot.get("mcp_servers", []):
                if server["status"] == "started":
                    origins.update({name: server["name"] for name in server["tools"]})
            system_prompt = self.persona_loader.load_admin_prompt()
            system_prompt += (
                "\n\n## Application runtime facts\n" + json.dumps(snapshot, ensure_ascii=False)
                + "\nThese application-supplied facts supersede old guesses in conversation "
                  "history about your capabilities. Use get_runtime_status for integration and "
                  "scheduler questions. Distinguish an MCP server from the data sources it exposes. "
                  "Do not claim that a loaded server is a live platform connection."
            )
        else:
            system_prompt = self.persona_loader.load_public_prompt()

        system_prompt += (
            f"\n\nReply tool destination for this turn: {target}. "
            "Contact lookups and reading other chats do not change this destination."
        )

        agent = Agent(
            model=create_model(self.model_config) if self.model_config is not None else None,
            system_prompt=system_prompt,
            tools=tools,
            conversation_manager=SummarizingConversationManager(),
            session_manager=FileSessionManager(
                session_id=session_id,
                storage_dir=self.storage_dir,
            ),
            callback_handler=None,
            hooks=[ToolAudit(origins)],
        )

        logger.debug("Created agent for phone %s (session_id=%s, reply_to=%s)", normalized, session_id, target)

        return AgentSession(
            phone=normalized,
            session_id=session_id,
            agent=agent,
        )

    def create_bootstrap(self, admin_phone: str, bootstrap_prompt: str) -> AgentSession:
        """Create a one-shot bootstrap agent for first-run setup.

        Uses the bootstrap prompt instead of SOUL.md, with only the tools
        needed for initial setup (persona updates + reply to admin).
        Session is persisted so the conversation carries into normal history.
        """
        from tools.whatsapp_admin import update_soul, update_user_profile

        normalized = normalize_phone(admin_phone)
        session_id = f"wa_{normalized}"

        reply_tool = make_reply_tool(self.wa_client, normalized)

        agent = Agent(
            model=create_model(self.model_config) if self.model_config is not None else None,
            system_prompt=bootstrap_prompt,
            tools=[update_soul, update_user_profile, reply_tool],
            conversation_manager=SummarizingConversationManager(),
            session_manager=FileSessionManager(
                session_id=session_id,
                storage_dir=self.storage_dir,
            ),
            callback_handler=None,
        )

        return AgentSession(
            phone=normalized,
            session_id=session_id,
            agent=agent,
        )
