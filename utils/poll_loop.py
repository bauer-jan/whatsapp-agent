"""Poll loop — routes incoming WhatsApp messages to agent sessions."""

from __future__ import annotations

import logging
import time

from utils.config import AgentConfig
from utils.agent_manager import AgentManager, AgentSession
from utils.token_tracker import track as track_usage
from utils.whatsapp_client import WhatsAppClient, WhatsAppMessage

logger = logging.getLogger(__name__)


def _phone_from_chat_id(chat_id: str | None) -> str | None:
    """Extract the phone number from a chat JID like '49151…@s.whatsapp.net'."""
    if not chat_id or "@s.whatsapp.net" not in chat_id:
        return None
    return chat_id.split("@")[0]


def is_allowed(sender: str, config: AgentConfig, chat_id: str | None = None) -> bool:
    """Check if *sender* (or the group *chat_id*) is permitted to receive a response.

    For DMs the sender may be a WhatsApp LID (not a phone number).
    In that case we fall back to the phone number embedded in chat_id.
    """
    if config.response_mode == "all":
        return True

    # Build a set of identifiers to check (sender + phone from chat_id)
    ids = {sender}
    chat_phone = _phone_from_chat_id(chat_id)
    if chat_phone:
        ids.add(chat_phone)

    if config.response_mode == "admin_only":
        return bool(ids & {config.admin_phone})
    if config.response_mode == "whitelist":
        if ids & {config.admin_phone}:
            return True
        if ids & set(config.whitelist):
            return True
        if chat_id and chat_id in config.whitelist:
            return True
        return False
    return False


def _inject_context(session: AgentSession, text: str) -> None:
    """Append a user message to session history without calling the LLM."""
    try:
        agent = session.agent
        message = {"role": "user", "content": [{"text": text}]}
        agent.messages.append(message)
        if agent._session_manager:
            agent._session_manager.append_message(message, agent)
    except Exception:
        logger.debug("Failed to inject context", exc_info=True)


def _handle_incoming(
    msg: WhatsAppMessage,
    session_manager: AgentManager,
) -> None:
    """Process an incoming message: run agent, let it decide whether to reply."""
    chat_type = "GROUP" if msg.is_group else "DM"
    reply_to = msg.chat_id if msg.is_group else msg.sender
    logger.info("▸ %s %s → %s", chat_type, msg.sender, msg.body)

    session = session_manager.get_or_create(msg.sender, reply_to=reply_to)
    prompt = f"[Message from {msg.sender} in chat {reply_to}]: {msg.body}"

    result = str(session.agent(prompt)).strip()

    usage = session.agent.event_loop_metrics.accumulated_usage
    tool_names = ",".join(session.agent.event_loop_metrics.tool_metrics.keys())
    track_usage(usage)

    inp = usage.get("inputTokens", 0)
    out = usage.get("outputTokens", 0)

    # If the agent used reply, the text response is just leftover thinking — skip it
    display = "(silent)" if not result or tool_names else result
    logger.info("▸ %s %s ← %s  [%d→%d tok, tools: %s]",
                chat_type, msg.sender, display, inp, out, tool_names or "-")


def _resolve_sender(msg: WhatsAppMessage) -> WhatsAppMessage:
    """Replace LID sender with the real phone from chat_id for incoming DMs.

    WhatsApp may deliver DMs with a LID as sender instead of the phone number.
    For incoming DMs the chat_id always contains the sender's real phone.
    """
    if msg.is_group or msg.is_from_me:
        return msg
    chat_phone = _phone_from_chat_id(msg.chat_id)
    if not chat_phone or chat_phone == msg.sender:
        return msg
    logger.debug("▸ LID resolved: %s → %s (from chat_id)", msg.sender, chat_phone)
    return WhatsAppMessage(
        sender=chat_phone, body=msg.body, timestamp=msg.timestamp,
        chat_id=msg.chat_id, is_group=False, is_from_me=False,
    )


def _route_own_group(
    msg: WhatsAppMessage, session_manager: AgentManager, config: AgentConfig,
) -> None:
    """Inject context for our own messages in a group chat."""
    if not is_allowed(config.admin_phone, config, chat_id=msg.chat_id):
        return
    logger.info("▸ GROUP %s (you): %s", msg.chat_id, msg.body)
    session = session_manager.get_or_create(msg.chat_id)
    _inject_context(session, f"[You wrote]: {msg.body}")


def _route_own_dm(
    msg: WhatsAppMessage, session_manager: AgentManager, config: AgentConfig,
) -> None:
    """Handle our own outgoing DMs: context injection or self-chat."""
    recipient = _phone_from_chat_id(msg.chat_id) or msg.chat_id

    if recipient == config.admin_phone:
        # Self-chat: treat as incoming admin message
        self_msg = WhatsAppMessage(
            sender=config.admin_phone, body=msg.body, timestamp=msg.timestamp,
            chat_id=msg.chat_id, is_group=False, is_from_me=False,
        )
        _handle_incoming(self_msg, session_manager)
        return

    if not is_allowed(recipient, config, chat_id=msg.chat_id):
        return
    logger.info("▸ DM → %s (you): %s", recipient, msg.body)
    session = session_manager.get_or_create(recipient)
    _inject_context(session, f"[You wrote to {recipient}]: {msg.body}")


def _route_message(
    msg: WhatsAppMessage, session_manager: AgentManager, config: AgentConfig,
) -> None:
    """Classify and route a single message to the right handler."""
    msg = _resolve_sender(msg)

    if msg.is_from_me:
        if msg.is_group:
            _route_own_group(msg, session_manager, config)
        else:
            _route_own_dm(msg, session_manager, config)
        return

    if not is_allowed(msg.sender, config, chat_id=msg.chat_id):
        logger.info("▸ blocked %s (chat=%s, mode=%s)", msg.sender, msg.chat_id, config.response_mode)
        return

    _handle_incoming(msg, session_manager)


def run(
    wa_client: WhatsAppClient,
    session_manager: AgentManager,
    config: AgentConfig,
    shutdown_flag: callable = lambda: False,
) -> None:
    """Poll WhatsApp for new messages and route them."""
    startup_ts = int(time.time())
    logger.info("Poll loop started (interval=%.1fs, mode=%s)", config.poll_interval, config.response_mode)

    while not shutdown_flag():
        try:
            for msg in wa_client.get_new_messages():
                if msg.timestamp < startup_ts:
                    logger.debug("▸ skip old msg (ts=%d < %d): %s", msg.timestamp, startup_ts, msg.body[:50])
                    continue

                logger.debug("▸ raw: sender=%s chat=%s from_me=%s group=%s body=%s",
                             msg.sender, msg.chat_id, msg.is_from_me, msg.is_group, msg.body[:50])
                try:
                    _route_message(msg, session_manager, config)
                except Exception:
                    logger.exception("Error routing message from %s", msg.sender)
        except Exception:
            logger.exception("Poll loop error")

        time.sleep(config.poll_interval)
