"""Property-based tests for MCPServerConfig parsing.

Uses Hypothesis to verify config round-trip integrity and invalid config rejection.
"""

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.config import MCPServerConfig

# --- Strategies ---

# Non-empty printable text (avoids control chars that could break things)
_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
)

_nonempty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=100,
)

_role_st = st.sampled_from(["admin", "public"])

_args_st = st.lists(_nonempty_text, max_size=10)

_env_st = st.one_of(
    st.none(),
    st.dictionaries(_nonempty_text, _nonempty_text, max_size=5),
)


@st.composite
def stdio_config_dicts(draw):
    """Generate valid stdio config dicts."""
    return {
        "name": draw(_name_st),
        "transport": "stdio",
        "command": draw(_nonempty_text),
        "args": draw(_args_st),
        "env": draw(_env_st),
        "role": draw(_role_st),
    }


@st.composite
def http_config_dicts(draw):
    """Generate valid http config dicts."""
    return {
        "name": draw(_name_st),
        "transport": "http",
        "url": draw(_nonempty_text),
        "role": draw(_role_st),
    }


valid_config_dicts = st.one_of(stdio_config_dicts(), http_config_dicts())


# --- Property 1: Config round-trip integrity ---
# Validates: Requirements 7.1, 7.2, 7.3, 1.1


class TestConfigRoundTripIntegrity:
    """Property 1: Config round-trip integrity.

    For any valid config dict, parsing via from_dict() preserves all fields,
    args is always a tuple of strings, and name is always a string.

    **Validates: Requirements 7.1, 7.2, 7.3, 1.1**
    """

    @given(raw=valid_config_dicts)
    @settings(max_examples=200)
    def test_all_fields_preserved(self, raw: dict):
        """Parsed config preserves all input field values."""
        cfg = MCPServerConfig.from_dict(raw)

        assert cfg.name == str(raw["name"])
        assert cfg.transport == raw["transport"]
        assert cfg.role == raw["role"]

        if raw["transport"] == "stdio":
            assert cfg.command == raw["command"]
            assert cfg.env == raw.get("env")
            expected_args = tuple(str(a) for a in raw.get("args", []))
            assert cfg.args == expected_args
        else:
            assert cfg.url == raw["url"]

    @given(raw=valid_config_dicts)
    @settings(max_examples=200)
    def test_args_is_always_tuple_of_strings(self, raw: dict):
        """args field is always a tuple of strings after parsing."""
        cfg = MCPServerConfig.from_dict(raw)

        assert isinstance(cfg.args, tuple)
        for item in cfg.args:
            assert isinstance(item, str)

    @given(raw=valid_config_dicts)
    @settings(max_examples=200)
    def test_name_is_always_string(self, raw: dict):
        """name field is always a string after parsing."""
        cfg = MCPServerConfig.from_dict(raw)
        assert isinstance(cfg.name, str)

    @given(raw=valid_config_dicts)
    @settings(max_examples=200)
    def test_role_is_valid(self, raw: dict):
        """role is always 'admin' or 'public' after parsing."""
        cfg = MCPServerConfig.from_dict(raw)
        assert cfg.role in ("admin", "public")


# --- Strategies for invalid configs ---

# Text that is guaranteed NOT to be "stdio" or "http"
_invalid_transport_st = _nonempty_text.filter(lambda t: t not in ("stdio", "http"))

# Text that is guaranteed NOT to be "admin" or "public"
_invalid_role_st = _nonempty_text.filter(lambda t: t not in ("admin", "public"))


# --- Property 2: Invalid config rejection ---
# Validates: Requirements 1.2, 1.3, 1.4


class TestInvalidConfigRejection:
    """Property 2: Invalid config rejection.

    For any config dict missing `name`, with invalid `transport`, or invalid `role`,
    MCPServerConfig.from_dict() should raise ValueError.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """

    @given(transport=st.sampled_from(["stdio", "http"]), role=_role_st)
    @settings(max_examples=100)
    def test_missing_name_raises(self, transport: str, role: str):
        """Config with missing name raises ValueError.

        **Validates: Requirements 1.2**
        """
        raw: dict[str, Any] = {
            "transport": transport,
            "command": "some-cmd",
            "url": "http://localhost:8080",
            "role": role,
        }
        with pytest.raises(ValueError, match="missing 'name'"):
            MCPServerConfig.from_dict(raw)

    @given(
        name=_name_st,
        falsy_name=st.sampled_from(["", None]),
        transport=st.sampled_from(["stdio", "http"]),
    )
    @settings(max_examples=100)
    def test_falsy_name_raises(self, name: str, falsy_name, transport: str):
        """Config with empty string or None name raises ValueError.

        **Validates: Requirements 1.2**
        """
        raw: dict[str, Any] = {
            "name": falsy_name,
            "transport": transport,
            "command": "some-cmd",
            "url": "http://localhost:8080",
        }
        with pytest.raises(ValueError, match="missing 'name'"):
            MCPServerConfig.from_dict(raw)

    @given(name=_name_st, bad_transport=_invalid_transport_st, role=_role_st)
    @settings(max_examples=200)
    def test_invalid_transport_raises(self, name: str, bad_transport: str, role: str):
        """Config with transport not in {"stdio", "http"} raises ValueError.

        **Validates: Requirements 1.3**
        """
        raw: dict[str, Any] = {
            "name": name,
            "transport": bad_transport,
            "command": "some-cmd",
            "url": "http://localhost:8080",
            "role": role,
        }
        with pytest.raises(ValueError, match="Invalid transport"):
            MCPServerConfig.from_dict(raw)

    @given(
        name=_name_st,
        transport=st.sampled_from(["stdio", "http"]),
        bad_role=_invalid_role_st,
    )
    @settings(max_examples=200)
    def test_invalid_role_raises(self, name: str, transport: str, bad_role: str):
        """Config with role not in {"admin", "public"} raises ValueError.

        **Validates: Requirements 1.4**
        """
        raw: dict[str, Any] = {
            "name": name,
            "transport": transport,
            "command": "some-cmd",
            "url": "http://localhost:8080",
            "role": bad_role,
        }
        with pytest.raises(ValueError, match="Invalid role"):
            MCPServerConfig.from_dict(raw)


# --- Property 3: Duplicate name rejection ---
# Validates: Requirement 1.9


class TestDuplicateNameRejection:
    """Property 3: Duplicate name rejection.

    For any list of MCP server configs where at least two entries share the
    same name, AgentConfig parsing should raise ValueError.

    **Validates: Requirement 1.9**
    """

    @given(name=_name_st, role=_role_st)
    @settings(max_examples=200)
    def test_duplicate_names_raise_valueerror(self, name: str, role: str):
        """Two MCP servers sharing the same generated name raises ValueError.

        **Validates: Requirement 1.9**
        """
        import tempfile

        from utils.config import AgentConfig

        content = (
            f'admin_phone: "123"\n'
            f"mcp_servers:\n"
            f'  - name: {_yaml_escape(name)}\n'
            f'    transport: "stdio"\n'
            f'    command: "cmd1"\n'
            f'    role: "{role}"\n'
            f'  - name: {_yaml_escape(name)}\n'
            f'    transport: "http"\n'
            f'    url: "http://localhost:8080"\n'
            f'    role: "{role}"\n'
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            f.flush()
            with pytest.raises(ValueError, match="Duplicate MCP server name"):
                AgentConfig.from_file(f.name)


def _yaml_escape(value: str) -> str:
    """Escape a string for safe YAML embedding."""
    # Use double-quoted YAML string with backslash escapes
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


# --- Property 7: Default values applied for omitted optional fields ---
# Validates: Requirements 1.7, 1.8


class TestDefaultValuesForOmittedFields:
    """Property 7: Default values applied for omitted optional fields.

    For any valid config dict that omits `role` and `args`, parsing should
    produce an MCPServerConfig with role=="admin" and args==().

    **Validates: Requirements 1.7, 1.8**
    """

    @given(name=_name_st, command=_nonempty_text)
    @settings(max_examples=200)
    def test_stdio_defaults_role_admin_and_args_empty(self, name: str, command: str):
        """Omitting role and args on stdio config gives role='admin', args=().

        **Validates: Requirements 1.7, 1.8**
        """
        raw: dict[str, Any] = {
            "name": name,
            "transport": "stdio",
            "command": command,
        }
        cfg = MCPServerConfig.from_dict(raw)
        assert cfg.role == "admin"
        assert cfg.args == ()

    @given(name=_name_st, url=_nonempty_text)
    @settings(max_examples=200)
    def test_http_defaults_role_admin_and_args_empty(self, name: str, url: str):
        """Omitting role and args on http config gives role='admin', args=().

        **Validates: Requirements 1.7, 1.8**
        """
        raw: dict[str, Any] = {
            "name": name,
            "transport": "http",
            "url": url,
        }
        cfg = MCPServerConfig.from_dict(raw)
        assert cfg.role == "admin"
        assert cfg.args == ()


# --- Unit tests for MCPServerConfig.from_dict() edge cases ---
# Requirements: 1.5, 1.6, 5.4


class TestMCPServerConfigEdgeCases:
    """Unit tests for MCPServerConfig.from_dict() edge cases.

    Tests missing command for stdio, missing url for http, args as string
    converted to list, and env passthrough.

    **Requirements: 1.5, 1.6, 5.4**
    """

    def test_stdio_missing_command_raises(self):
        """stdio transport without command raises ValueError.

        **Validates: Requirement 1.5**
        """
        raw: dict[str, Any] = {
            "name": "test-server",
            "transport": "stdio",
        }
        with pytest.raises(ValueError, match="requires 'command'"):
            MCPServerConfig.from_dict(raw)

    def test_http_missing_url_raises(self):
        """http transport without url raises ValueError.

        **Validates: Requirement 1.6**
        """
        raw: dict[str, Any] = {
            "name": "test-server",
            "transport": "http",
        }
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPServerConfig.from_dict(raw)

    def test_args_string_converted_to_tuple(self):
        """A single string for args is converted to a one-element tuple.

        **Validates: Requirement 5.4**
        """
        raw: dict[str, Any] = {
            "name": "test-server",
            "transport": "stdio",
            "command": "npx",
            "args": "--help",
        }
        cfg = MCPServerConfig.from_dict(raw)
        assert cfg.args == ("--help",)
        assert isinstance(cfg.args, tuple)

    def test_env_dict_passthrough(self):
        """env dict is passed through to the config unchanged.

        **Validates: Requirement 5.4**
        """
        env = {"FOO": "bar", "BAZ": "qux"}
        raw: dict[str, Any] = {
            "name": "test-server",
            "transport": "stdio",
            "command": "npx",
            "env": env,
        }
        cfg = MCPServerConfig.from_dict(raw)
        assert cfg.env == {"FOO": "bar", "BAZ": "qux"}
