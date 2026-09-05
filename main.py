"""WhatsApp Agent — entry point and startup orchestration."""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from utils import (
    AgentConfig, HeartbeatLoop, MCPManager, PersonaLoader,
    AgentManager, WhatsAppClient,
    run_poll_loop, track_usage, log_token_totals,
)
from tools import (
    ToolManager, ALL_ADMIN_TOOLS, ALL_PUBLIC_TOOLS,
    init_admin_tools,
)

from utils.model_factory import validate_model_credentials

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    logger.info("Received signal %s — shutting down", signal.Signals(signum).name)
    _shutdown = True


def _wait_for_whatsapp(wa_client: WhatsAppClient, timeout: int = 60) -> None:
    """Block until WhatsApp connects or timeout expires."""
    logger.info("WhatsApp connecting (waiting up to %ds)…", timeout)
    for _ in range(timeout):
        if wa_client.connection_error:
            raise ConnectionError(wa_client.connection_error)
        if wa_client.is_connected():
            logger.info("WhatsApp connected")
            return
        time.sleep(1)
    if wa_client.connection_error:
        raise ConnectionError(wa_client.connection_error)
    if wa_client.is_connected():
        logger.info("WhatsApp connected")
        return
    raise ConnectionError(
        "WhatsApp did not connect within the pairing timeout. "
        "Restart and scan the QR code; model tasks have not been started."
    )


def _run_bootstrap(config: AgentConfig, persona_loader: PersonaLoader, session_manager: AgentManager) -> None:
    """Run the first-run bootstrap conversation if BOOTSTRAP.md exists."""
    bootstrap = persona_loader.load_bootstrap()
    if not bootstrap:
        return

    bootstrap_path = Path(config.persona_dir) / "BOOTSTRAP.md"
    logger.info("First run detected — running bootstrap")
    try:
        session = session_manager.create_bootstrap(config.admin_phone, bootstrap)
        session.agent(
            "Send your first message. One short text, 1-2 sentences. "
            "Introduce yourself as James and ask their name. Nothing else."
        )
        track_usage(session.agent.event_loop_metrics.accumulated_usage)
        bootstrap_path.unlink(missing_ok=True)
        logger.info("Bootstrap complete")
    except Exception:
        logger.exception("Bootstrap failed — will retry next startup")


def _send_startup_notice(config: AgentConfig, wa_client: WhatsAppClient,
                         mcp_manager: MCPManager, heartbeat: HeartbeatLoop) -> bool:
    """Send one deterministic ready notice; does not require model inference."""
    servers = mcp_manager.status_snapshot()
    started = [s for s in servers if s["status"] == "started"]
    unavailable = [s["name"] for s in servers if s["status"] != "started"]
    integrations = ", ".join(f"{s['name']} ({len(s['tools'])} tools)" for s in started) or "none loaded"
    tasks = heartbeat.status_snapshot()["configured_tasks"]
    text = f"James is online. MCP: {integrations}. {len(tasks)} recurring task(s) configured."
    if unavailable:
        text += " MCP unavailable: " + ", ".join(unavailable) + "."
    text += " Ask me what tools are available."
    sent = wa_client.send_message(config.admin_phone, text)
    if sent:
        logger.info("Startup notice sent to admin")
    else:
        logger.warning("Startup notice could not be sent to admin")
    return sent


def main() -> None:
    config = AgentConfig.from_file()
    validate_model_credentials(config.model)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s.%(msecs)03d %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.log_file)],
        force=True,  # Neonize configures the root logger during import.
    )

    # Silence noisy third-party loggers
    for name in ("strands.telemetry", "strands.agent", "strands.event_loop", "strands.session.repository_session_manager"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("─── Agent starting ───")
    logger.info("▸ admin=%s  mode=%s  poll=%.1fs",
                config.admin_phone, config.response_mode, config.poll_interval)

    startup_ts = int(time.time())
    wa_client = WhatsAppClient()
    try:
        wa_client.connect()
        _wait_for_whatsapp(wa_client)
    except (ConnectionError, KeyboardInterrupt) as error:
        wa_client.disconnect()
        logger.error("Startup stopped: %s", error or "interrupted")
        raise SystemExit(1) from None

    persona_loader = PersonaLoader(persona_dir=config.persona_dir, admin_phone=config.admin_phone)
    persona_loader.ensure_persona_files()

    tool_manager = ToolManager(admin_phone=config.admin_phone)
    init_admin_tools(wa_client=wa_client, persona_dir=config.persona_dir)

    mcp_manager = MCPManager(list(config.mcp_servers))
    mcp_manager.start_all()

    admin_tools = ALL_ADMIN_TOOLS + mcp_manager.get_admin_tools()
    public_tools = ALL_PUBLIC_TOOLS + mcp_manager.get_public_tools()
    tool_manager.register_admin_tools(admin_tools)
    tool_manager.register_public_tools(public_tools)

    mcp_admin_count = len(mcp_manager.get_admin_tools())
    mcp_public_count = len(mcp_manager.get_public_tools())
    logger.info(
        "▸ tools: %d admin (%d native + %d mcp), %d public (%d native + %d mcp)",
        len(admin_tools), len(ALL_ADMIN_TOOLS), mcp_admin_count,
        len(public_tools), len(ALL_PUBLIC_TOOLS), mcp_public_count,
    )

    heartbeat = None

    def runtime_context():
        return {
            "mcp_inventory_available": True,
            "mcp_servers": mcp_manager.status_snapshot(),
            "whatsapp_connected": wa_client.is_connected(),
            "response_mode": config.response_mode,
            "heartbeat": heartbeat.status_snapshot() if heartbeat is not None else {"running": False},
        }

    session_manager = AgentManager(
        storage_dir=config.session_storage_dir,
        persona_loader=persona_loader,
        tool_manager=tool_manager,
        wa_client=wa_client,
        model_config=config.model,
        runtime_context_provider=runtime_context,
    )

    _run_bootstrap(config, persona_loader, session_manager)

    heartbeat = HeartbeatLoop(
        persona_loader=persona_loader,
        agent_manager=session_manager,
        admin_phone=config.admin_phone,
        usage_callback=track_usage,
    )
    heartbeat.start()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("─── Agent ready ───")

    try:
        _send_startup_notice(config, wa_client, mcp_manager, heartbeat)
        run_poll_loop(wa_client, session_manager, config, shutdown_flag=lambda: _shutdown,
                      startup_ts=startup_ts)
    finally:
        heartbeat.stop()
        mcp_manager.stop_all()
        wa_client.disconnect()
        log_token_totals()
        logger.info("─── Agent shut down ───")


if __name__ == "__main__":
    main()
