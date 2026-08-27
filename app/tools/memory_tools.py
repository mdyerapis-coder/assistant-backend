"""remember/forget/search_past_conversations — the model's interface to
app/memory.py, wrapped as OpenAI-schema tools. Kept separate from memory.py
so that module stays framework-free and independently testable.
"""

import json

from .. import memory
from .registry import ToolSpec, register


async def _remember(key: str, value: str) -> str:
    return await memory.remember(key, value)


async def _forget(key: str) -> str:
    return await memory.forget(key)


async def _search_past_conversations(query: str) -> str:
    results = await memory.search_past_conversations(query)
    if not results:
        return "No past messages matched that search."
    return json.dumps(results)


register(
    ToolSpec(
        name="remember",
        description=(
            "Store a durable fact about the user (preference, standing "
            "commitment, timezone, etc.) that should be available in every "
            "future conversation, not just this one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "short, stable identifier, e.g. 'timezone'",
                },
                "value": {"type": "string", "description": "the fact to remember"},
            },
            "required": ["key", "value"],
        },
        fn=_remember,
    )
)

register(
    ToolSpec(
        name="forget",
        description="Remove a previously remembered fact by its key.",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        fn=_forget,
    )
)

register(
    ToolSpec(
        name="search_past_conversations",
        description=(
            "Search prior conversation history for a keyword or phrase. Use "
            "this when the user references something discussed before that "
            "isn't in the current conversation or in remembered facts."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        fn=_search_past_conversations,
    )
)
