"""Log tool execution evidence without arguments, messages or full tool results."""
import json
import logging
import uuid

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)


class ToolAudit(HookProvider):
    def __init__(self, origins: dict[str, str] | None = None):
        self.origins = origins or {}
        self.invocation_id = uuid.uuid4().hex[:12]

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get('name', 'unknown')
        result = event.result
        status = result.get('status', 'unknown') if isinstance(result, dict) else 'error'
        retrieved = None
        if isinstance(result, dict):
            for block in result.get('content', []):
                payload = block.get('json')
                text = block.get('text', '')
                if isinstance(text, str) and text.startswith(('Error:', 'Failed to ')):
                    status = 'error'
                if payload is None and isinstance(text, str):
                    try:
                        payload = json.loads(text)
                    except (ValueError, TypeError):
                        pass
                if isinstance(payload, dict):
                    # Only emit syntactically valid timestamp fields, never arbitrary text.
                    retrieved = self._timestamp(payload.get('retrieved_at')) or retrieved
        logger.info(
            'Tool completed (invocation=%s, tool=%s, origin=%s, status=%s, retrieved_at=%s)',
            self.invocation_id, name, self.origins.get(name, 'native'), status,
            retrieved or '-',
        )

    @staticmethod
    def _timestamp(value):
        from datetime import datetime
        if not isinstance(value, str) or len(value) > 40:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed.isoformat() if parsed.tzinfo is not None else None
