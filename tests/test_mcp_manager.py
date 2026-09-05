"""Unit tests for MCPManager (Task 3.1)."""

from unittest.mock import MagicMock, patch

import pytest

from utils.config import MCPServerConfig
from utils.mcp_manager import MCPManager


def _stdio_config(name="test-server", role="admin"):
    return MCPServerConfig(
        name=name,
        transport="stdio",
        command="echo",
        args=("hello",),
        role=role,
    )


def _http_config(name="http-server", role="public"):
    return MCPServerConfig(
        name=name,
        transport="http",
        url="http://localhost:8080/mcp",
        role=role,
    )


class TestMCPManagerInit:
    def test_empty_configs(self):
        mgr = MCPManager([])
        assert mgr.get_admin_tools() == []
        assert mgr.get_public_tools() == []

    def test_stores_configs(self):
        configs = [_stdio_config(), _http_config()]
        mgr = MCPManager(configs)
        assert mgr._server_configs == configs
        assert mgr._clients == {}


class TestMakeTransportCallable:
    def test_stdio_returns_callable(self):
        config = _stdio_config()
        transport = MCPManager._make_transport_callable(config)
        assert callable(transport)

    def test_http_returns_callable(self):
        config = _http_config()
        transport = MCPManager._make_transport_callable(config)
        assert callable(transport)

    def test_unknown_transport_raises(self):
        config = MCPServerConfig(
            name="bad", transport="grpc", command="x"
        )
        with pytest.raises(ValueError, match="Unknown transport: grpc"):
            MCPManager._make_transport_callable(config)


class TestStartAll:
    @patch("utils.mcp_manager.MCPClient")
    def test_admin_tools_partitioned(self, mock_mcp_cls):
        fake_tools = [MagicMock(name="tool1"), MagicMock(name="tool2")]
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = fake_tools
        mock_mcp_cls.return_value = mock_client

        mgr = MCPManager([_stdio_config(role="admin")])
        mgr.start_all()

        assert mgr.get_admin_tools() == fake_tools
        assert mgr.get_public_tools() == []
        assert "test-server" in mgr._clients

    @patch("utils.mcp_manager.MCPClient")
    def test_public_tools_partitioned(self, mock_mcp_cls):
        fake_tools = [MagicMock(name="tool1")]
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = fake_tools
        mock_mcp_cls.return_value = mock_client

        mgr = MCPManager([_http_config(role="public")])
        mgr.start_all()

        assert mgr.get_public_tools() == fake_tools
        assert mgr.get_admin_tools() == []

    @patch("utils.mcp_manager.MCPClient")
    def test_mixed_roles(self, mock_mcp_cls):
        admin_tools = [MagicMock(name="admin_t")]
        public_tools = [MagicMock(name="public_t")]

        def side_effect(_transport):
            client = MagicMock()
            # Track which call this is
            if mock_mcp_cls.call_count == 1:
                client.list_tools_sync.return_value = admin_tools
            else:
                client.list_tools_sync.return_value = public_tools
            return client

        mock_mcp_cls.side_effect = side_effect

        mgr = MCPManager([
            _stdio_config(name="s1", role="admin"),
            _http_config(name="s2", role="public"),
        ])
        mgr.start_all()

        assert mgr.get_admin_tools() == admin_tools
        assert mgr.get_public_tools() == public_tools
        assert len(mgr._clients) == 2

    @patch("utils.mcp_manager.MCPClient")
    def test_failed_server_skipped(self, mock_mcp_cls):
        mock_mcp_cls.return_value.start.side_effect = RuntimeError("boom")

        mgr = MCPManager([_stdio_config()])
        mgr.start_all()  # should not raise

        assert mgr.get_admin_tools() == []
        assert mgr._clients == {}

    @patch("utils.mcp_manager.MCPClient")
    def test_partial_failure(self, mock_mcp_cls):
        """One server fails, the other succeeds — tools from success are kept."""
        good_tools = [MagicMock(name="good_tool")]
        call_count = 0

        def side_effect(_transport):
            nonlocal call_count
            call_count += 1
            client = MagicMock()
            if call_count == 1:
                client.start.side_effect = RuntimeError("fail")
            else:
                client.list_tools_sync.return_value = good_tools
            return client

        mock_mcp_cls.side_effect = side_effect

        mgr = MCPManager([
            _stdio_config(name="bad", role="admin"),
            _stdio_config(name="good", role="admin"),
        ])
        mgr.start_all()

        assert mgr.get_admin_tools() == good_tools
        assert len(mgr._clients) == 1
        assert "good" in mgr._clients


class TestStopAll:
    @patch("utils.mcp_manager.MCPClient")
    def test_stop_all_calls_stop_on_each(self, mock_mcp_cls):
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = []
        mock_mcp_cls.return_value = mock_client

        mgr = MCPManager([_stdio_config()])
        mgr.start_all()
        mgr.stop_all()

        mock_client.stop.assert_called_once_with(None, None, None)
        assert mgr._clients == {}

    def test_stop_all_no_clients(self):
        mgr = MCPManager([])
        mgr.stop_all()  # should not raise
        assert mgr._clients == {}

    @patch("utils.mcp_manager.MCPClient")
    def test_stop_error_does_not_propagate(self, mock_mcp_cls):
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = []
        mock_client.stop.side_effect = RuntimeError("stop failed")
        mock_mcp_cls.return_value = mock_client

        mgr = MCPManager([_stdio_config()])
        mgr.start_all()
        mgr.stop_all()  # should not raise

        assert mgr._clients == {}

    @patch("utils.mcp_manager.MCPClient")
    def test_stop_called_on_all_even_if_one_fails(self, mock_mcp_cls):
        """If first client raises on stop, second still gets stopped."""
        clients = []

        def side_effect(_transport):
            client = MagicMock()
            client.list_tools_sync.return_value = []
            clients.append(client)
            return client

        mock_mcp_cls.side_effect = side_effect

        mgr = MCPManager([
            _stdio_config(name="s1"),
            _stdio_config(name="s2"),
        ])
        mgr.start_all()

        # First client raises on stop
        clients[0].stop.side_effect = RuntimeError("fail")

        mgr.stop_all()

        clients[0].stop.assert_called_once()
        clients[1].stop.assert_called_once()
        assert mgr._clients == {}


class TestStartStopLifecycle:
    """Unit tests for MCPManager start/stop lifecycle.

    Requirements: 2.1, 2.4, 3.3
    """

    @patch("utils.mcp_manager.MCPClient")
    def test_start_all_succeeding_registers_all_clients(self, mock_mcp_cls):
        """All servers succeed → all N clients are active with correct tools.

        Validates: Requirement 2.1
        """
        clients = []

        def make_client(_transport):
            client = MagicMock()
            tool = MagicMock(name=f"tool_{len(clients)}")
            client.list_tools_sync.return_value = [tool]
            clients.append(client)
            return client

        mock_mcp_cls.side_effect = make_client

        configs = [
            _stdio_config(name="s1", role="admin"),
            _stdio_config(name="s2", role="admin"),
            _http_config(name="s3", role="public"),
        ]
        mgr = MCPManager(configs)
        mgr.start_all()

        assert len(mgr._clients) == 3
        assert "s1" in mgr._clients
        assert "s2" in mgr._clients
        assert "s3" in mgr._clients
        # Each client was started
        for c in clients:
            c.start.assert_called_once()

    @patch("utils.mcp_manager.MCPClient")
    def test_stop_all_after_partial_start(self, mock_mcp_cls):
        """First server fails, second succeeds → stop_all only stops the successful one.

        Validates: Requirements 2.4, 3.3
        """
        clients = []
        call_count = 0

        def make_client(_transport):
            nonlocal call_count
            call_count += 1
            client = MagicMock()
            if call_count == 1:
                client.start.side_effect = RuntimeError("fail")
            else:
                client.list_tools_sync.return_value = []
            clients.append(client)
            return client

        mock_mcp_cls.side_effect = make_client

        mgr = MCPManager([
            _stdio_config(name="failing"),
            _stdio_config(name="working"),
        ])
        mgr.start_all()

        assert len(mgr._clients) == 1
        assert "working" in mgr._clients

        mgr.stop_all()

        # Only the successful client gets stop() called
        clients[1].stop.assert_called_once_with(None, None, None)
        # The failed client was never added, so stop is never called on it
        clients[0].stop.assert_not_called()
        assert mgr._clients == {}


@patch("utils.mcp_manager.MCPClient")
def test_discovery_failure_stops_started_client(mock_client_class):
    client = mock_client_class.return_value
    client.list_tools_sync.side_effect = RuntimeError("Discovery failed")
    manager = MCPManager([_stdio_config()])
    manager.start_all()
    client.stop.assert_called_once_with(None, None, None)
    assert not manager._clients
    assert manager.get_admin_tools() == []


@patch("utils.mcp_manager.MCPClient")
def test_repeated_start_and_restart_do_not_duplicate_tools(mock_client_class):
    tool = MagicMock()
    mock_client_class.return_value.list_tools_sync.return_value = [tool]
    manager = MCPManager([_stdio_config()])
    manager.start_all()
    manager.start_all()
    mock_client_class.return_value.start.assert_called_once()
    assert manager.get_admin_tools() == [tool]
    manager.stop_all()
    assert manager.get_admin_tools() == []
    manager.start_all()
    assert manager.get_admin_tools() == [tool]
    manager.stop_all()
