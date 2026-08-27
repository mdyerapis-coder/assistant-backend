"""get_current_time — trivial no-I/O tool that returns the current UTC
time as an ISO 8601 string. Exists to prove the tool-calling seam
(registry → chat loop → Android ChatReducer) end-to-end before a real
tool is wired up.
"""

from datetime import datetime, timezone

from .registry import ToolSpec, register


async def _get_current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


register(
    ToolSpec(
        name="get_current_time",
        description=(
            "Return the current UTC time as an ISO 8601 string. Use when "
            "the user asks what time or date it is, or for any answer that "
            "depends on the current moment."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_get_current_time,
    )
)
