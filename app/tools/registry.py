"""Flat, append-only tool registry. See docs/adr/009.

Add a tool by calling register(ToolSpec(...)) — nothing else needs
touching, chat.py reads this list and never branches on tool names itself.

`always_visible` tools go into every OpenAI `tools=[...]` call. Anything
registered with `always_visible=False` is reached later via
`list_skills()`/`use_skill()` (phase 03+, not built yet — see the ADR) so
the per-request tool-schema cost doesn't grow with every future capability.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ToolFn = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the function's arguments
    fn: ToolFn
    always_visible: bool = True


TOOLS: list[ToolSpec] = []


def register(spec: ToolSpec) -> None:
    TOOLS.append(spec)


def always_visible_tools() -> list[ToolSpec]:
    return [t for t in TOOLS if t.always_visible]


def get_tool(name: str) -> ToolSpec | None:
    return next((t for t in TOOLS if t.name == name), None)


def openai_tool_defs(specs: list[ToolSpec]) -> list[dict]:
    """Render ToolSpecs into the OpenAI tools=[...] wire format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in specs
    ]
