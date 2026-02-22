# Personal AI Assistant + MCP Support

A personal AI assistant that runs on your own devices. You communicate with the agent through a WhatsApp self-chat. No API keys are required. It connects directly to WhatsApp Web via QR code, just like you would in a browser, polls for messages, and responds using an LLM on Amazon Bedrock.

The agent can schedule tasks and access other systems through MCP, including email, the internet, services, and databases. Just add them via the config file. 

Similar to OpenClaw, the agent includes structured system files such as `SOUL.md`, `USER.md`, and `HEARTBEAT.md` to create a identity for the user and agent.

Built with [Strands Agents](https://github.com/strands-agents/sdk-python) and [neonize](https://github.com/krypton-byte/neonize).

![Screenshot](/logo.png)

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

**Scan the QR code with WhatsApp on first run. The agent will send you a short intro message, learn your name and preferences over a few messages, then write its own SOUL.md and USER.md. The file is deleted after bootstrap completes and won't run again.**

### Configuration

```yaml
admin_phone: "5511999999999"    # Your phone number (digits only, include country prefix, eg. for Germany 49XXXX)
response_mode: "whitelist"      # all | admin_only | whitelist
whitelist:                      # phone numbers or group JIDs
  # - "5522888888888"
  # - "120363001234567890@g.us"
poll_interval: 5.0
persona_dir: "persona/"
session_storage_dir: "sessions/"
log_level: "INFO"
log_file: "agent.log"

## Add Additional MCP Configurations
#mcp_servers:
#  - name: "filesystem"
#    transport: "stdio"
#    command: "npx"
#    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
#    role: "admin"
```

`response_mode` controls who gets a reply:
- `all` — everyone (not recommended — any number triggers LLM calls)
- `admin_only` — only you
- `whitelist` — you + listed numbers and groups

## Design decisions

**Session-per-number isolation** — Each phone number gets its own Strands agent instance with separate conversation history via `FileSessionManager`. No cross-contamination.

**Agent decides when to respond** — The agent receives messages as context and explicitly calls `reply` or `write_message` tools to send. If it has nothing to say, it stays silent. No auto-forwarding.

**It becomes someone** — On first run, the agent starts a conversation with you (BOOTSTRAP.md) to figure out its name, personality, and vibe. Then it writes its own SOUL.md. From that point on, it has a persistent identity.

**Filesystem as Persona** — The agent's identity and behavior are plain markdown files on disk. No database. The agent reads them on every message and can update them at runtime.

**Per-task heartbeat scheduling** — Background tasks defined in HEARTBEAT.md run on individual intervals (`[every N min]` syntax). The agent can check in or do anything else autonomously while nobody's talking to it.


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
