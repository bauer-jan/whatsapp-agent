"""WhatsApp Web client wrapper using neonize (whatsmeow Python bindings)."""

import logging
import queue
import re
import threading
from dataclasses import dataclass
from collections import deque

from neonize.client import NewClient
from neonize.events import (
    ClientOutdatedEv, ConnectedEv, ConnectFailureEv, DisconnectedEv, MessageEv,
)

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
        self._recent_messages: deque[WhatsAppMessage] = deque(maxlen=1000)
        self._recent_lock = threading.Lock()
        self._connected = False
        self.connection_error: str | None = None
        self._connection_thread: threading.Thread | None = None
        self._register_handlers()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Register neonize event handlers that feed the inbox queue."""

        @self.client.event(ConnectedEv)
        def on_connected(_client: NewClient, _event: ConnectedEv) -> None:
            self.connection_error = None
            self._connected = True
            logger.info("WhatsApp Web connected")

        @self.client.event(ClientOutdatedEv)
        def on_outdated(_client: NewClient, _event: ClientOutdatedEv) -> None:
            self._connected = False
            self.connection_error = (
                "WhatsApp rejected this client as outdated. Update neonize and restart James."
            )
            logger.error(self.connection_error)

        @self.client.event(ConnectFailureEv)
        def on_failure(_client: NewClient, _event: ConnectFailureEv) -> None:
            self._connected = False
            self.connection_error = "WhatsApp connection failed; inspect the preceding client log."
            logger.error(self.connection_error)

        @self.client.event(DisconnectedEv)
        def on_disconnected(_client: NewClient, _event: DisconnectedEv) -> None:
            self._connected = False

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
                sender_phone = self._phone_for_jid(src.Sender, src.SenderAlt)
                sender = sender_phone or f"{src.Sender.User}@{src.Sender.Server}"
                chat_jid = src.Chat
                chat_id = f"{chat_jid.User}@{chat_jid.Server}"
                if not src.IsGroup:
                    # SenderAlt identifies an incoming DM's peer; RecipientAlt
                    # identifies the recipient of an own outgoing DM.
                    alternate = src.RecipientAlt if src.IsFromMe else src.SenderAlt
                    chat_phone = self._phone_for_jid(chat_jid, alternate)
                    if chat_phone:
                        chat_id = f"{chat_phone}@s.whatsapp.net"
                logger.info(
                    "Received text event (from_me=%s, group=%s, sender_type=%s, "
                    "chat_type=%s, phone_resolved=%s)",
                    bool(src.IsFromMe), bool(src.IsGroup), src.Sender.Server,
                    src.Chat.Server, bool(sender_phone),
                )

                parsed = WhatsAppMessage(
                    sender=sender,
                    body=text,
                    timestamp=int(event.Info.Timestamp),
                    chat_id=chat_id,
                    is_group=bool(src.IsGroup),
                    is_from_me=bool(src.IsFromMe),
                )
                with self._recent_lock:
                    self._recent_messages.append(parsed)
                self._inbox.put(parsed)
            except Exception:
                logger.exception("Failed to parse incoming message")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _phone_for_jid(self, jid, alternate=None) -> str | None:
        """Resolve a real phone JID; never relabel a LID as a phone number."""
        for candidate in (jid, alternate):
            if candidate is not None and candidate.Server == "s.whatsapp.net" and candidate.User:
                return normalize_phone(str(candidate.User))
        if jid.Server == "lid":
            try:
                mapped = self.client.get_pn_from_lid(jid)
                if mapped.Server == "s.whatsapp.net" and mapped.User:
                    return normalize_phone(str(mapped.User))
            except Exception:
                logger.debug("Phone mapping unavailable for LID", exc_info=True)
            logger.info("Unresolved WhatsApp LID; retaining its original identity")
        return None

    def connect(self) -> None:
        """Start neonize client in a daemon thread. Displays QR code for auth."""
        self.connection_error = None

        def connect_client() -> None:
            try:
                self.client.connect()
            except Exception:
                self._connected = False
                self.connection_error = "WhatsApp client could not connect; inspect the client log."
                logger.exception("WhatsApp connection thread failed")

        self._connection_thread = threading.Thread(
            target=connect_client, name="james-whatsapp-connection", daemon=True,
        )
        self._connection_thread.start()
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

    def get_recent_messages(self, chat: str, limit: int = 10) -> list[WhatsAppMessage]:
        """Read a bounded local buffer, including chats blocked from automatic replies.

        Only text events received during this process are available; this does
        not fetch old WhatsApp history or trigger any model calls or sends.
        """
        target = chat if "@" in chat else f"{normalize_phone(chat)}@s.whatsapp.net"
        with self._recent_lock:
            return [m for m in self._recent_messages if m.chat_id == target][-limit:]

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

    def disconnect(self) -> None:
        """Release the native client when startup fails or James shuts down."""
        self._connected = False
        try:
            # Neonize >=0.4 starts a non-daemon native worker. disconnect()
            # closes only the socket; stop() cancels its Go context as well.
            self.client.stop()
            thread = self._connection_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
                if thread.is_alive():
                    logger.warning("WhatsApp connection worker is still stopping")
                else:
                    self._connection_thread = None
        except Exception:
            logger.exception("Error disconnecting WhatsApp client")

    def is_connected(self) -> bool:
        """Return current connection status."""
        return self._connected
