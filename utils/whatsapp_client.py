"""WhatsApp Web client wrapper using neonize (whatsmeow Python bindings)."""

import logging
import queue
import re
import threading
from dataclasses import dataclass

from neonize.client import NewClient
from neonize.events import ConnectedEv, MessageEv

logger = logging.getLogger(__name__)


@dataclass
class WhatsAppMessage:
    """A parsed incoming WhatsApp text message."""

    sender: str
    body: str
    timestamp: int
    chat_id: str
    is_group: bool
    is_from_me: bool


def normalize_phone(phone: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return re.sub(r"\D", "", phone)


class WhatsAppClient:
    """Thin wrapper around neonize that bridges its event-driven API into a
    pull-based queue the poll loop can drain."""

    def __init__(self, db_path: str = "whatsapp.sqlite3") -> None:
        self.client = NewClient(db_path)
        self._inbox: queue.Queue[WhatsAppMessage] = queue.Queue()
        self._connected = False
        self._register_handlers()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Register neonize event handlers that feed the inbox queue."""

        @self.client.event(ConnectedEv)
        def on_connected(_client: NewClient, _event: ConnectedEv) -> None:
            self._connected = True
            logger.info("WhatsApp Web connected")

        @self.client.event(MessageEv)
        def on_message(_client: NewClient, event: MessageEv) -> None:
            src = event.Info.MessageSource

            # Debug log before any parsing — useful for LID diagnostics
            try:
                logger.debug(
                    "▸ neonize event: sender=%s sender_alt=%s chat=%s from_me=%s group=%s",
                    getattr(getattr(src, "Sender", None), "User", "?"),
                    getattr(getattr(src, "SenderAlt", None), "User", "?"),
                    getattr(getattr(src, "Chat", None), "User", "?"),
                    getattr(src, "IsFromMe", "?"),
                    getattr(src, "IsGroup", "?"),
                )
            except Exception:
                logger.debug("▸ neonize event: (could not read MessageSource)")

            # Extract text body (plain or extended)
            try:
                msg = event.Message
                text = msg.conversation or getattr(
                    getattr(msg, "extendedTextMessage", None), "text", None,
                )
            except Exception:
                logger.debug("Failed to read message payload", exc_info=True)
                return

            if not text:
                return

            # Build WhatsAppMessage and enqueue
            try:
                sender = normalize_phone(str(src.Sender.User))
                chat_jid = src.Chat
                chat_id = f"{chat_jid.User}@{chat_jid.Server}"

                # LID chats have no real phone in chat_id — use sender instead
                if "@lid" in chat_id and sender:
                    chat_id = f"{sender}@s.whatsapp.net"

                self._inbox.put(WhatsAppMessage(
                    sender=sender,
                    body=text,
                    timestamp=int(event.Info.Timestamp),
                    chat_id=chat_id,
                    is_group=bool(src.IsGroup),
                    is_from_me=bool(src.IsFromMe),
                ))
            except Exception:
                logger.exception("Failed to parse incoming message")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Start neonize client in a daemon thread. Displays QR code for auth."""
        thread = threading.Thread(target=self.client.connect, daemon=True)
        thread.start()
        logger.info("WhatsApp client connecting (scan QR code if prompted)")

    def get_new_messages(self) -> list[WhatsAppMessage]:
        """Drain the inbox queue. Non-blocking."""
        messages: list[WhatsAppMessage] = []
        while not self._inbox.empty():
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return messages

    def send_message(self, recipient: str, text: str) -> bool:
        """Send a text message to a phone number or group chat.

        Args:
            recipient: Phone number (digits) or group chat JID (contains @g.us).
            text: Message text.

        Returns True on success, False on failure.
        """
        try:
            from neonize.utils.jid import build_jid

            if "@" in recipient:
                parts = recipient.split("@", 1)
                jid = build_jid(parts[0], server=parts[1])
            else:
                jid = build_jid(normalize_phone(recipient))
            self.client.send_message(jid, text)
            logger.info("▸ sent → %s: %s", recipient, text)
            return True
        except Exception:
            logger.exception("Failed to send message to %s", recipient)
            return False

    def is_connected(self) -> bool:
        """Return current connection status."""
        return self._connected
