"""MCP server lifecycle management and tool loading."""

import logging
from typing import Any

from strands.tools.mcp import MCPClient

from utils.config import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPManager:
    """Owns the lifecycle of all MCPClient instances.

    Starts them, loads tools, partitions by role, and stops them.
    """

    def __init__(self, server_configs: list[MCPServerConfig]) -> None:
        self._server_configs = server_configs
        self._admin_tools: list[Any] = []
        self._public_tools: list[Any] = []
        self._clients: dict[str, MCPClient] = {}

    @staticmethod
    def _make_transport_callable(config: MCPServerConfig):
        """Create the transport callable for an MCPClient based on config."""
        if config.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env=config.env,
            )
            return lambda: stdio_client(params)

        elif config.transport == "http":
            from mcp.client.streamable_http import streamablehttp_client

            return lambda: streamablehttp_client(config.url)

        raise ValueError(f"Unknown transport: {config.transport}")

    def start_all(self) -> None:
        """Start all configured MCP servers and load their tools."""
        for server_config in self._server_configs:
            try:
                transport_callable = self._make_transport_callable(server_config)
                client = MCPClient(transport_callable)
                client.start()

                tools = client.list_tools_sync()

                if server_config.role == "admin":
                    self._admin_tools.extend(tools)
                else:
                    self._public_tools.extend(tools)

                self._clients[server_config.name] = client
                logger.info(
                    "MCP server '%s' started (%d tools)",
                    server_config.name,
                    len(tools),
                )
            except Exception:
                logger.exception(
                    "Failed to start MCP server '%s' — skipping",
                    server_config.name,
                )

    def get_admin_tools(self) -> list[Any]:
        """Return tools from MCP servers with role 'admin'."""
        return self._admin_tools

    def get_public_tools(self) -> list[Any]:
        """Return tools from MCP servers with role 'public'."""
        return self._public_tools

    def stop_all(self) -> None:
        """Stop all running MCP clients and release resources."""
        for name, client in self._clients.items():
            try:
                client.stop(None, None, None)
                logger.info("MCP server '%s' stopped", name)
            except Exception:
                logger.exception(
                    "Error stopping MCP server '%s'", name
                )
        self._clients.clear()
