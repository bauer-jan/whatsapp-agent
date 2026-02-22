"""Unit tests for AgentConfig (Task 1.2)."""

import pytest

from utils.config import AgentConfig, VALID_RESPONSE_MODES


@pytest.fixture
def config_file(tmp_path):
    """Helper to write a YAML config file and return its path."""
    def _write(content: str) -> str:
        p = tmp_path / "config.yaml"
        p.write_text(content)
        return str(p)
    return _write


class TestAgentConfigMissingRequired:
    """Test missing required config fields raise descriptive errors."""

    def test_missing_admin_phone_raises(self, config_file):
        path = config_file("response_mode: all\n")
        with pytest.raises(ValueError, match="admin_phone"):
            AgentConfig.from_file(path)

    def test_empty_admin_phone_raises(self, config_file):
        path = config_file("admin_phone: \n")
        with pytest.raises(ValueError, match="admin_phone"):
            AgentConfig.from_file(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            AgentConfig.from_file("/nonexistent/config.yaml")


class TestAgentConfigDefaults:
    """Test default values for optional config fields."""

    def test_defaults(self, config_file):
        path = config_file('admin_phone: "5511999999999"\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.admin_phone == "5511999999999"
        assert cfg.persona_dir == "persona/"
        assert cfg.session_storage_dir == "sessions/"
        assert cfg.poll_interval == 5.0
        assert cfg.response_mode == "all"
        assert cfg.whitelist == ()
        assert cfg.log_level == "INFO"
        assert cfg.log_file == "agent.log"
    """Test WHATSAPP_WHITELIST parsing from comma-separated string."""

    def test_whitelist_as_list(self, config_file):
        path = config_file(
            'admin_phone: "123"\nwhitelist:\n  - "111"\n  - "222"\n'
        )
        cfg = AgentConfig.from_file(path)
        assert cfg.whitelist == ("111", "222")

    def test_whitelist_as_csv_string(self, config_file):
        path = config_file('admin_phone: "123"\nwhitelist: "111, 222, 333"\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.whitelist == ("111", "222", "333")

    def test_whitelist_empty(self, config_file):
        path = config_file('admin_phone: "123"\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.whitelist == ()


class TestInvalidResponseMode:
    """Test invalid WHATSAPP_RESPONSE_MODE values."""

    def test_invalid_mode_raises(self, config_file):
        path = config_file('admin_phone: "123"\nresponse_mode: "invalid"\n')
        with pytest.raises(ValueError, match="Invalid response_mode"):
            AgentConfig.from_file(path)

    @pytest.mark.parametrize("mode", sorted(VALID_RESPONSE_MODES))
    def test_valid_modes_accepted(self, config_file, mode):
        path = config_file(f'admin_phone: "123"\nresponse_mode: "{mode}"\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.response_mode == mode


class TestMCPServersInAgentConfig:
    """Test mcp_servers parsing in AgentConfig.from_file()."""

    def test_no_mcp_servers_key_defaults_empty(self, config_file):
        path = config_file('admin_phone: "123"\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.mcp_servers == ()

    def test_empty_mcp_servers_list(self, config_file):
        path = config_file('admin_phone: "123"\nmcp_servers: []\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.mcp_servers == ()

    def test_mcp_servers_null_defaults_empty(self, config_file):
        path = config_file('admin_phone: "123"\nmcp_servers:\n')
        cfg = AgentConfig.from_file(path)
        assert cfg.mcp_servers == ()

    def test_single_stdio_server_parsed(self, config_file):
        content = (
            'admin_phone: "123"\n'
            "mcp_servers:\n"
            '  - name: "fs"\n'
            '    transport: "stdio"\n'
            '    command: "npx"\n'
            "    args: [-y, server-fs]\n"
        )
        path = config_file(content)
        cfg = AgentConfig.from_file(path)
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0].name == "fs"
        assert cfg.mcp_servers[0].transport == "stdio"
        assert cfg.mcp_servers[0].command == "npx"
        assert cfg.mcp_servers[0].args == ("-y", "server-fs")
        assert cfg.mcp_servers[0].role == "admin"

    def test_multiple_servers_parsed(self, config_file):
        content = (
            'admin_phone: "123"\n'
            "mcp_servers:\n"
            '  - name: "fs"\n'
            '    transport: "stdio"\n'
            '    command: "npx"\n'
            '  - name: "web"\n'
            '    transport: "http"\n'
            '    url: "http://localhost:8080/mcp"\n'
            '    role: "public"\n'
        )
        path = config_file(content)
        cfg = AgentConfig.from_file(path)
        assert len(cfg.mcp_servers) == 2
        assert cfg.mcp_servers[0].name == "fs"
        assert cfg.mcp_servers[1].name == "web"
        assert cfg.mcp_servers[1].role == "public"

    def test_duplicate_names_raises(self, config_file):
        content = (
            'admin_phone: "123"\n'
            "mcp_servers:\n"
            '  - name: "fs"\n'
            '    transport: "stdio"\n'
            '    command: "npx"\n'
            '  - name: "fs"\n'
            '    transport: "http"\n'
            '    url: "http://localhost/mcp"\n'
        )
        path = config_file(content)
        with pytest.raises(ValueError, match="Duplicate MCP server name: 'fs'"):
            AgentConfig.from_file(path)

    def test_invalid_server_entry_propagates(self, config_file):
        content = (
            'admin_phone: "123"\n'
            "mcp_servers:\n"
            "  - transport: stdio\n"
            "    command: npx\n"
        )
        path = config_file(content)
        with pytest.raises(ValueError, match="missing 'name'"):
            AgentConfig.from_file(path)

    def test_mcp_servers_is_tuple(self, config_file):
        content = (
            'admin_phone: "123"\n'
            "mcp_servers:\n"
            '  - name: "fs"\n'
            '    transport: "stdio"\n'
            '    command: "npx"\n'
        )
        path = config_file(content)
        cfg = AgentConfig.from_file(path)
        assert isinstance(cfg.mcp_servers, tuple)
