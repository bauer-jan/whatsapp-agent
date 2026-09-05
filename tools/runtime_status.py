"""Admin-only access to application-provided runtime facts."""
import json
from collections.abc import Callable

from strands import tool


def make_runtime_status_tool(snapshot: Callable[[], dict]):
    @tool
    def get_runtime_status() -> str:
        """Inspect James's actual registered tools, MCP servers, model and scheduler.

        Use when the admin asks what you can do, which integrations are loaded,
        or what is scheduled. The app supplies this information; do not guess
        from old conversation history. Server startup status is not a live
        reachability test. This does not query platform telemetry or send messages.
        """
        return json.dumps(snapshot(), ensure_ascii=False)

    return get_runtime_status
