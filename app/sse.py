"""Encodes ChatEvent-shaped dicts as `data: {...}\n\n` SSE frames.

Owning source for docs/CONTRACT.md — if they disagree, that's a bug, fix
both in the same commit. See that doc for the six event types and their
fields. Every event dict also carries `conversation_id`, satisfying the
contract's "the first event of the response includes the assigned id".
"""
from typing import Any

try:
    import orjson

    def encode_event(event: dict[str, Any]) -> str:
        return f"data: {orjson.dumps(event).decode()}\n\n"

    def decode_event(line: str) -> dict[str, Any]:
        # Hot path first: data: frames skip the strip() allocation in the
        # common case. Bare "[DONE]" (no data: prefix) is checked only on
        # the fallthrough path.
        if line.startswith("data:"):
            payload = line[5:].lstrip()
            if not payload:
                return {"type": "unknown"}
            if payload == "[DONE]":
                return {"type": "message_completed"}
            try:
                obj = orjson.loads(payload)
                t = obj.get("type")
                if t not in ("delta", "tool_call_started", "tool_call_progress", "tool_call_finished", "message_completed", "error"):
                    return {"type": "unknown", "conversation_id": obj.get("conversation_id", "")}
                return obj
            except Exception:
                return {"type": "unknown"}
        if line.strip() == "[DONE]":
            return {"type": "message_completed"}
        return {"type": "unknown"}

except ImportError:
    import json as _json

    def encode_event(event: dict[str, Any]) -> str:
        return f"data: {_json.dumps(event)}\n\n"

    def decode_event(line: str) -> dict[str, Any]:
        if line.startswith("data:"):
            payload = line[5:].lstrip()
            if not payload:
                return {"type": "unknown"}
            if payload == "[DONE]":
                return {"type": "message_completed"}
            try:
                obj = _json.loads(payload)
                t = obj.get("type")
                if t not in ("delta", "tool_call_started", "tool_call_progress", "tool_call_finished", "message_completed", "error"):
                    return {"type": "unknown", "conversation_id": obj.get("conversation_id", "")}
                return obj
            except Exception:
                return {"type": "unknown"}
        if line.strip() == "[DONE]":
            return {"type": "message_completed"}
        return {"type": "unknown"}


DONE = "data: [DONE]\n\n"
