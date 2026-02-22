# WhatsApp AI Agent + MCP Support

A personal AI assistant that lives on WhatsApp. Built with [Strands Agents](https://github.com/strands-agents/sdk-python) and [neonize](https://github.com/krypton-byte/neonize). You can add MCP servers for mor functionalities!

No API keys, no cloud messaging service — it connects directly to WhatsApp Web via QR code, polls for messages, and responds through an LLM on Amazon Bedrock.

[]![Screenshot](/logo.png)

```
You (WhatsApp) → neonize → poll loop → Strands Agent (LLM) → tools/MCP Server → neonize → WhatsApp
```

## MCP servers

Extend the agent with external tools by registering [MCP](https://modelcontextprotocol.io/) servers in `config.yaml`. Tools are discovered automatically at startup and injected into the existing permission pipeline alongside native tools.

```yaml
mcp_servers:
  - name: "filesystem"
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    role: "admin"

  - name: "weather"
    transport: "http"
    url: "http://localhost:3001/mcp"
    role: "public"
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique identifier for the server |
| `transport` | yes | `stdio` (local process) or `http` (remote) |
| `command` | stdio only | Executable to run |
| `args` | no | Command arguments (default: empty) |
| `env` | no | Environment variables for stdio process |
| `url` | http only | Server URL |
| `role` | no | `admin` or `public` (default: `admin`) |

Tools from `admin` servers are only available to the admin user. Tools from `public` servers are available to everyone — same rules as native tools.

If a server fails to start, the agent logs the error and continues with the remaining servers. No MCP servers configured? The agent behaves exactly as before.


## Design decisions

**Session-per-phone isolation** — Each phone number gets its own Strands agent instance with separate conversation history via `FileSessionManager`. No cross-contamination.

**Agent decides when to respond** — The agent receives messages as context and explicitly calls `reply` or `write_message` tools to send. If it has nothing to say, it stays silent. No auto-forwarding.

**Zero-cost context injection** — Your outgoing messages (DMs and group chats) are written directly to the session history without triggering an LLM call. The agent sees them as prior context next time it responds.

**It becomes someone** — On first run, the agent starts a conversation with you (BOOTSTRAP.md) to figure out its name, personality, and vibe. Then it writes its own SOUL.md. From that point on, it has a persistent identity.

**Filesystem as Persona** — The agent's identity and behavior are plain markdown files on disk. No database. The agent reads them on every message and can update them at runtime.

**Per-task heartbeat scheduling** — Background tasks defined in HEARTBEAT.md run on individual intervals (`[every N min]` syntax). The agent can check in or do anything else autonomously while nobody's talking to it.

**WhatsApp LID resolution** — WhatsApp may deliver messages with a LID (Linked ID) instead of the sender's phone number. The poll loop transparently resolves LIDs to real phone numbers using the chat JID, so routing and session isolation work correctly regardless.


## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- AWS credentials configured (Amazon Bedrock for the LLM)

### Setup

```bash
cp config.yaml.example config.yaml
# Edit config.yaml — set admin_phone to your number
uv sync
uv run main.py
```

Scan the QR code with WhatsApp on first run. Sessions persist in `whatsapp.sqlite3` after that.

### First run (bootstrap)

To trigger the bootstrap conversation, copy the template:

```bash
cp templates/BOOTSTRAP.md persona/BOOTSTRAP.md
```

The agent will send you a short intro message, learn your name and preferences over a few messages, then write its own SOUL.md and USER.md. The file is deleted after bootstrap completes and won't run again.

### Configuration

```yaml
admin_phone: "5511999999999"    # Your phone number (digits only)
response_mode: "whitelist"      # all | admin_only | whitelist
whitelist:                      # phone numbers or group JIDs
  # - "5522888888888"
  # - "120363001234567890@g.us"
poll_interval: 5.0
persona_dir: "persona/"
session_storage_dir: "sessions/"
log_level: "INFO"
log_file: "agent.log"
```

`response_mode` controls who gets a reply:
- `all` — everyone (not recommended — any number triggers LLM calls)
- `admin_only` — only you
- `whitelist` — you + listed numbers and groups

## Persona system

Markdown files in `persona/` define everything about the agent. On first run, SOUL.md, USER.md, and HEARTBEAT.md are copied from `templates/`.

| File | What it does |
|------|-------------|
| `SOUL.md` | Personality, communication style, boundaries |
| `USER.md` | What the agent knows about you (admin prompt only) |
| `HEARTBEAT.md` | Periodic background tasks with `[every N min]` intervals |
| `BOOTSTRAP.md` | First-run conversation to establish identity (deleted after use) |

The agent updates these at runtime via `update_soul`, `update_user_profile`, and `update_heartbeat` tools. Templates in `templates/` are never modified.

## Message routing

| Scenario | What happens |
|----------|-------------|
| You DM the agent (self-chat) | Agent responds via `reply` tool |
| You DM someone else | Silently injected into that contact's session (zero tokens) |
| You message a group | Silently injected into that group's session (zero tokens) |
| Someone DMs the agent | Agent responds via `reply` tool (if allowed by response_mode) |
| Someone messages a group | Agent responds to the group via `reply` tool (if allowed) |

## Tools

Injected based on who's talking to the agent via `ToolManager`.

**Admin gets all tools:**
- `reply` — respond to the current conversation (baked-in target via closure)
- `write_message` — send to any phone number or group
- `lookup_contact` — search contacts and groups by name or number
- `update_soul` / `update_user_profile` / `update_heartbeat` — edit persona files

**Public users get:**
- `reply` — respond to the current conversation
- `read_message` — acknowledge conversation context

The agent cannot call admin tools in a public session — `ToolManager` resolves the sender's role and injects only the permitted set.

## Architecture

```
main.py                # Entry point, startup orchestration, bootstrap
config.yaml            # Runtime config (gitignored)
tools/
  tool_manager.py      # Permission-based tool injection (Admin / Public)
  whatsapp_admin.py    # Admin tools: write_message, lookup_contact, persona updates
  whatsapp_public.py   # Public tools: reply (closure factory), read_message
utils/
  whatsapp_client.py   # Neonize WhatsApp Web wrapper + message queue
  agent_manager.py     # Per-phone Strands agent creation with FileSessionManager
  poll_loop.py         # Message polling, LID resolution, routing, context injection
  config.py            # AgentConfig from YAML
  persona_loader.py    # Persona file loading, prompt assembly, heartbeat parsing
  heartbeat.py         # Background task executor with per-task intervals
  token_tracker.py     # Cumulative token usage tracking
templates/             # Read-only defaults (copied to persona/ on first run)
persona/               # Live agent identity (updated at runtime, gitignored)
tests/                 # Unit and property-based tests
```

## Deploy (EC2)

```bash
# Full deploy: package → S3 → install on EC2 → restart agent
./deploy.sh eu-central-1 i-0abc123def456

# Package a release tarball and upload to EC2 home dir (no redeploy)
./deploy.sh --github
```

On the EC2 instance:
```bash
export BUCKET=wa-agent-ACCOUNT-REGION
./install.sh                    # preserves persona/ and sessions/
./install.sh --reset-templates  # overwrites persona/ from templates/
./install.sh --clean-sessions   # wipes conversation history
```

## Tests

```bash
uv run pytest tests/ -v
```

MCP-specific tests:

```bash
# Config parsing (unit + property-based)
uv run pytest tests/test_config.py tests/test_mcp_config_properties.py -v

# MCPManager lifecycle (unit + property-based)
uv run pytest tests/test_mcp_manager.py tests/test_mcp_manager_properties.py -v
```

Manual integration test — add an MCP server to `config.yaml` and start the agent. Look for:

```
MCP server 'filesystem' started (X tools)
▸ tools: N admin (M native + X mcp), ...
```

If the server binary isn't available, the agent logs the error and continues with native tools only.

## License

MIT
