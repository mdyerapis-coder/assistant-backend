"""list_plugins / enable_plugin / disable_plugin — the model's interface
to app/plugins.py, wrapped as OpenAI-schema tools.
"""

from __future__ import annotations

import json

from .. import plugins
from .registry import ToolSpec, register


async def _list_plugins() -> str:
    infos = await plugins.list_plugins()
    return json.dumps(infos)


async def _enable_plugin(name: str) -> str:
    return await plugins.enable_plugin(name)


async def _disable_plugin(name: str) -> str:
    return await plugins.disable_plugin(name)


register(
    ToolSpec(
        name="list_plugins",
        description=(
            "List all installed extension plugins, their enabled/disabled status, "
            "version, description, and counts of provided tools and skills."
        ),
        parameters={"type": "object", "properties": {}},
        fn=_list_plugins,
        always_visible=True,
    )
)

register(
    ToolSpec(
        name="enable_plugin",
        description="Enable an installed plugin by its name, activating its tools and skills.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "name of the plugin to enable"}
            },
            "required": ["name"],
        },
        fn=_enable_plugin,
        always_visible=True,
    )
)

register(
    ToolSpec(
        name="disable_plugin",
        description="Disable an active plugin by its name, unloading its tools and skills.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "name of the plugin to disable"}
            },
            "required": ["name"],
        },
        fn=_disable_plugin,
        always_visible=True,
    )
)
