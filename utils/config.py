"""Agent configuration loaded from a YAML config file."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_RESPONSE_MODES = {"all", "admin_only", "whitelist"}
DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass(frozen=True)
class AgentConfig:
    admin_phone: str
    persona_dir: str = "persona/"
    session_storage_dir: str = "sessions/"
    poll_interval: float = 5.0
    response_mode: str = "all"
    whitelist: tuple[str, ...] = ()
    log_level: str = "INFO"
    log_file: str = "agent.log"

    @classmethod
    def from_file(cls, path: str | None = None) -> "AgentConfig":
        config_path = Path(path or os.environ.get("AGENT_CONFIG", DEFAULT_CONFIG_PATH))
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text()) or {}

        admin_phone = raw.get("admin_phone")
        if not admin_phone:
            raise ValueError("Missing required config field: admin_phone")

        response_mode = raw.get("response_mode", "all")
        if response_mode not in VALID_RESPONSE_MODES:
            raise ValueError(
                f"Invalid response_mode: '{response_mode}'. "
                f"Valid values: {', '.join(sorted(VALID_RESPONSE_MODES))}"
            )

        whitelist = raw.get("whitelist") or []
        if isinstance(whitelist, str):
            whitelist = [p.strip() for p in whitelist.split(",") if p.strip()]
        else:
            whitelist = [str(p).strip() for p in whitelist]

        return cls(
            admin_phone=str(admin_phone),
            persona_dir=raw.get("persona_dir", "persona/"),
            session_storage_dir=raw.get("session_storage_dir", "sessions/"),
            poll_interval=float(raw.get("poll_interval", 5.0)),
            response_mode=response_mode,
            whitelist=tuple(whitelist),
            log_level=raw.get("log_level", "INFO"),
            log_file=raw.get("log_file", "agent.log"),
        )
