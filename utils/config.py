"""Agent configuration loaded from a YAML config file."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_RESPONSE_MODES = {"all", "admin_only", "whitelist"}
VALID_TRANSPORTS = {"stdio", "http"}
VALID_ROLES = {"admin", "public"}
DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass(frozen=True)
class MCPServerConfig:
    """A single MCP server definition from config."""

    name: str
    transport: str  # "stdio" or "http"
    command: str | None = None  # stdio: executable path
    args: tuple[str, ...] = ()  # stdio: command arguments
    env: dict[str, str] | None = None  # stdio: environment variables
    url: str | None = None  # http: server URL
    role: str = "admin"  # "admin" or "public"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MCPServerConfig":
        """Parse a single MCP server entry from config YAML."""
        name = raw.get("name")
        if not name:
            raise ValueError("MCP server config missing 'name'")

        transport = raw.get("transport", "stdio")
        if transport not in VALID_TRANSPORTS:
            raise ValueError(
                f"Invalid transport '{transport}' for MCP server '{name}'"
            )

        role = raw.get("role", "admin")
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}' for MCP server '{name}'")

        if transport == "stdio" and not raw.get("command"):
            raise ValueError(
                f"MCP server '{name}' with stdio transport requires 'command'"
            )
        if transport == "http" and not raw.get("url"):
            raise ValueError(
                f"MCP server '{name}' with http transport requires 'url'"
            )

        args = raw.get("args", [])
        if isinstance(args, str):
            args = [args]

        return cls(
            name=str(name),
            transport=transport,
            command=raw.get("command"),
            args=tuple(str(a) for a in args),
            env=raw.get("env"),
            url=raw.get("url"),
            role=role,
        )


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
    mcp_servers: tuple[MCPServerConfig, ...] = ()

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

        # Parse MCP server configs
        raw_mcp = raw.get("mcp_servers") or []
        mcp_servers = tuple(MCPServerConfig.from_dict(entry) for entry in raw_mcp)

        # Validate no duplicate server names
        seen_names: set[str] = set()
        for srv in mcp_servers:
            if srv.name in seen_names:
                raise ValueError(
                    f"Duplicate MCP server name: '{srv.name}'"
                )
            seen_names.add(srv.name)

        return cls(
            admin_phone=str(admin_phone),
            persona_dir=raw.get("persona_dir", "persona/"),
            session_storage_dir=raw.get("session_storage_dir", "sessions/"),
            poll_interval=float(raw.get("poll_interval", 5.0)),
            response_mode=response_mode,
            whitelist=tuple(whitelist),
            log_level=raw.get("log_level", "INFO"),
            log_file=raw.get("log_file", "agent.log"),
            mcp_servers=mcp_servers,
        )
