"""WhatsApp Agent — entry point and startup orchestration."""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from utils import (
    AgentConfig, HeartbeatLoop, PersonaLoader,
    AgentManager, WhatsAppClient,
    run_poll_loop, track_usage, log_token_totals,
)
from tools import (
    ToolManager, ALL_ADMIN_TOOLS, ALL_PUBLIC_TOOLS,
    init_admin_tools,
)

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
        if wa_client.is_connected():
            break
        time.sleep(1)
    logger.info("WhatsApp %s", "connected" if wa_client.is_connected() else "NOT connected — continuing")


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
            "Just say hi and ask their name. Nothing else."
        )
        track_usage(session.agent.event_loop_metrics.accumulated_usage)
        bootstrap_path.unlink(missing_ok=True)
        logger.info("Bootstrap complete")
    except Exception:
        logger.exception("Bootstrap failed — will retry next startup")


def main() -> None:
    config = AgentConfig.from_file()

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s.%(msecs)03d %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.log_file)],
    )

    # Silence noisy third-party loggers
    for name in ("strands.telemetry", "strands.agent", "strands.event_loop"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("─── Agent starting ───")
    logger.info("▸ admin=%s  mode=%s  poll=%.1fs",
                config.admin_phone, config.response_mode, config.poll_interval)

    wa_client = WhatsAppClient()
    wa_client.connect()
    _wait_for_whatsapp(wa_client)

    persona_loader = PersonaLoader(persona_dir=config.persona_dir, admin_phone=config.admin_phone)
    persona_loader.ensure_persona_files()

    tool_manager = ToolManager(admin_phone=config.admin_phone)
    init_admin_tools(wa_client=wa_client, persona_dir=config.persona_dir)
    tool_manager.register_admin_tools(ALL_ADMIN_TOOLS)
    tool_manager.register_public_tools(ALL_PUBLIC_TOOLS)
    logger.info("▸ tools: %d admin, %d public", len(ALL_ADMIN_TOOLS), len(ALL_PUBLIC_TOOLS))

    session_manager = AgentManager(
        storage_dir=config.session_storage_dir,
        persona_loader=persona_loader,
        tool_manager=tool_manager,
        wa_client=wa_client,
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
        run_poll_loop(wa_client, session_manager, config, shutdown_flag=lambda: _shutdown)
    finally:
        heartbeat.stop()
        log_token_totals()
        logger.info("─── Agent shut down ───")


if __name__ == "__main__":
    main()
