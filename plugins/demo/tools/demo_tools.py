"""Demo tool registered by the demo plugin."""

from app.tools.registry import ToolSpec, register


async def _greet(name: str = "friend") -> str:
    return f"Hello, {name}! This is from the demo plugin."


register(
    ToolSpec(
        name="plugin_demo_greet",
        description="Greet someone using the demo plugin.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        fn=_greet,
        always_visible=False,
    )
)
