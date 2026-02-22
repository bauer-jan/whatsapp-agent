"""Property-based tests for MCPManager lifecycle and tool loading.

Uses Hypothesis to verify tool partitioning, graceful degradation,
and shutdown resilience with mocked MCPClient instances.
"""

from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.config import MCPServerConfig
from utils.mcp_manager import MCPManager

# --- Strategies ---

_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
)

_role_st = st.sampled_from(["admin", "public"])


@st.composite
def server_config_lists(draw, min_size=1, max_size=8):
    """Generate lists of MCPServerConfig with unique names and mixed roles."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    names = draw(
        st.lists(_name_st, min_size=n, max_size=n, unique=True)
    )
    configs = []
    for name in names:
        role = draw(_role_st)
        configs.append(
            MCPServerConfig(
                name=name,
                transport="stdio",
                command="echo",
                args=("hello",),
                role=role,
            )
        )
    return configs


# --- Property 4: Tool partitioning by role ---
# Validates: Requirements 4.1, 4.2, 4.3


class TestToolPartitioningByRole:
    """Property 4: Tool partitioning by role.

    For any list of MCP server configs with mixed admin/public roles,
    after start_all(), every tool from an admin server appears only in
    get_admin_tools() and every tool from a public server appears only
    in get_public_tools(), and the two sets are disjoint.

    **Validates: Requirements 4.1, 4.2, 4.3**
    """

    @given(configs=server_config_lists(min_size=1, max_size=6))
    @settings(max_examples=200)
    @patch("utils.mcp_manager.MCPClient")
    def test_tools_partitioned_by_role(self, mock_mcp_cls, configs):
        """Admin server tools go to admin set, public to public set, disjoint.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        # Build per-server tool sets so we can verify partitioning
        expected_admin = []
        expected_public = []
        tools_by_index = {}

        for i, cfg in enumerate(configs):
            tool = MagicMock(name=f"tool_{cfg.name}_{i}")
            tools_by_index[i] = [tool]
            if cfg.role == "admin":
                expected_admin.append(tool)
            else:
                expected_public.append(tool)

        call_idx = 0

        def make_client(_transport):
            nonlocal call_idx
            client = MagicMock()
            client.list_tools_sync.return_value = tools_by_index[call_idx]
            call_idx += 1
            return client

        mock_mcp_cls.side_effect = make_client

        mgr = MCPManager(configs)
        mgr.start_all()

        admin_tools = mgr.get_admin_tools()
        public_tools = mgr.get_public_tools()

        # Every expected admin tool is in admin set
        for tool in expected_admin:
            assert tool in admin_tools

        # Every expected public tool is in public set
        for tool in expected_public:
            assert tool in public_tools

        # No admin tool appears in public set
        for tool in expected_admin:
            assert tool not in public_tools

        # No public tool appears in admin set
        for tool in expected_public:
            assert tool not in admin_tools

        # Sets are disjoint (by identity)
        admin_ids = {id(t) for t in admin_tools}
        public_ids = {id(t) for t in public_tools}
        assert admin_ids.isdisjoint(public_ids)


# --- Property 5: Graceful degradation preserves active count ---
# Validates: Requirements 3.1, 3.2


@st.composite
def configs_with_failures(draw, max_size=6):
    """Generate N server configs and a subset of indices that should fail."""
    configs = draw(server_config_lists(min_size=1, max_size=max_size))
    n = len(configs)
    fail_indices = draw(
        st.frozensets(st.integers(min_value=0, max_value=n - 1), max_size=n)
    )
    return configs, fail_indices


class TestGracefulDegradation:
    """Property 5: Graceful degradation preserves active count.

    For any list of N server configs where K servers fail to start,
    start_all() should result in exactly N-K active clients, and all
    tools from the successful servers should be available.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(data=configs_with_failures())
    @settings(max_examples=200)
    @patch("utils.mcp_manager.MCPClient")
    def test_active_count_equals_n_minus_k(self, mock_mcp_cls, data):
        """Exactly N-K clients are active after K failures.

        **Validates: Requirements 3.1, 3.2**
        """
        configs, fail_indices = data
        n = len(configs)
        k = len(fail_indices)

        successful_tools = []
        call_idx = 0

        def make_client(_transport):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            client = MagicMock()
            if idx in fail_indices:
                client.start.side_effect = RuntimeError(f"fail-{idx}")
            else:
                tool = MagicMock(name=f"tool_{idx}")
                client.list_tools_sync.return_value = [tool]
                successful_tools.append(tool)
            return client

        mock_mcp_cls.side_effect = make_client

        mgr = MCPManager(configs)
        mgr.start_all()

        # Exactly N-K active clients
        assert len(mgr._clients) == n - k

        # All tools from successful servers are available
        all_tools = mgr.get_admin_tools() + mgr.get_public_tools()
        for tool in successful_tools:
            assert tool in all_tools


# --- Property 6: Shutdown resilience ---
# Validates: Requirements 2.3, 2.5


@st.composite
def configs_with_stop_failures(draw, max_size=6):
    """Generate N server configs and a subset of indices whose stop() raises."""
    configs = draw(server_config_lists(min_size=1, max_size=max_size))
    n = len(configs)
    fail_indices = draw(
        st.frozensets(st.integers(min_value=0, max_value=n - 1), max_size=n)
    )
    return configs, fail_indices


class TestShutdownResilience:
    """Property 6: Shutdown resilience.

    For any set of active MCPClients, stop_all() should call stop() on
    every client. If any client raises during stop(), the remaining
    clients should still have stop() called.

    **Validates: Requirements 2.3, 2.5**
    """

    @given(data=configs_with_stop_failures())
    @settings(max_examples=200)
    @patch("utils.mcp_manager.MCPClient")
    def test_stop_called_on_every_client(self, mock_mcp_cls, data):
        """stop() is called on every client regardless of exceptions.

        **Validates: Requirements 2.3, 2.5**
        """
        configs, fail_indices = data
        clients = []
        call_idx = 0

        def make_client(_transport):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            client = MagicMock()
            client.list_tools_sync.return_value = []
            if idx in fail_indices:
                client.stop.side_effect = RuntimeError(f"stop-fail-{idx}")
            clients.append(client)
            return client

        mock_mcp_cls.side_effect = make_client

        mgr = MCPManager(configs)
        mgr.start_all()

        # All servers started successfully, so all are active
        assert len(mgr._clients) == len(configs)

        # stop_all should not raise
        mgr.stop_all()

        # stop() was called on every client
        for client in clients:
            client.stop.assert_called_once_with(None, None, None)

        # clients dict is cleared
        assert mgr._clients == {}
