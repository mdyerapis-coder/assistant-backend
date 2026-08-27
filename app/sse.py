"""Encodes ChatEvent-shaped dicts as `data: {...}\\n\\n` SSE frames.

Owning source for docs/CONTRACT.md — if they disagree, that's a bug, fix
both in the same commit. See that doc for the six event types and their
fields. Every event dict also carries `conversation_id`, satisfying the
contract's "the first event of the response includes the assigned id".
"""

import json
from typing import Any


def encode_event(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


DONE = "data: [DONE]\n\n"
