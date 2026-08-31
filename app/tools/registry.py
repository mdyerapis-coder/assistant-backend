"""Flat, append-only tool registry. See docs/adr/009.

Add a tool by calling register(ToolSpec(...)) — nothing else needs
touching, chat.py reads this list and never branches on tool names itself.

`always_visible` tools go into every OpenAI `tools=[...]` call. Anything
registered with `always_visible=False` is reached later via
`list_skills()`/`use_skill()` (phase 03+, not built yet — see the ADR) so
the per-request tool-schema cost doesn't grow with every future capability.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

ToolFn = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the function's arguments
    fn: ToolFn
    always_visible: bool = True


TOOLS: list[ToolSpec] = []
_TOOL_MAP: dict[str, ToolSpec] = {}
_VISIBLE_CACHE: list[ToolSpec] | None = None
_DEFS_CACHE: dict[int, list[dict]] = {}


def register(spec: ToolSpec) -> None:
    TOOLS.append(spec)
    _TOOL_MAP[spec.name] = spec
    global _VISIBLE_CACHE
    _VISIBLE_CACHE = None
    _DEFS_CACHE.clear()


def unregister(names: Iterable[str]) -> None:
    global TOOLS, _VISIBLE_CACHE
    name_set = set(names)
    TOOLS = [t for t in TOOLS if t.name not in name_set]
    for n in name_set:
        _TOOL_MAP.pop(n, None)
    _VISIBLE_CACHE = None
    _DEFS_CACHE.clear()


def always_visible_tools() -> list[ToolSpec]:
    global _VISIBLE_CACHE
    if _VISIBLE_CACHE is None:
        _VISIBLE_CACHE = [t for t in TOOLS if t.always_visible]
    return _VISIBLE_CACHE


def get_tool(name: str) -> ToolSpec | None:
    return _TOOL_MAP.get(name)


def openai_tool_defs(specs: list[ToolSpec]) -> list[dict]:
    """Render ToolSpecs into the OpenAI tools=[...] wire format."""
    key = id(specs)
    if key in _DEFS_CACHE:
        return _DEFS_CACHE[key]
    defs = [
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
    _DEFS_CACHE[key] = defs
    return defs
