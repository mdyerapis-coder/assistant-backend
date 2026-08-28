"""FastAPI application entry point.

Run locally: uvicorn app.main:app --reload
Run in production: see assistant.service (systemd unit shipped in phase 00).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from . import db, mcp_client, patterns, plugins, scheduler, skills
from .routers import chat, device_tokens, health, oauth_google
from .tools import calendar as calendar_tools  # noqa: F401  registers calendar tools
from .tools import gmail as gmail_tools  # noqa: F401  registers gmail tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.connect()
    await patterns.prune_old_patterns()
    skills_dir = Path(__file__).parent.parent / "skills"
    skills.load_skills(skills_dir)
    logger.info("Loaded %d skills from %s", len(skills.all_skills()), skills_dir)
    mcp_config_path = Path(__file__).parent.parent / "mcp_servers.json"
    mcp_configs = mcp_client.load_mcp_config(mcp_config_path)
    await mcp_client.start_all(mcp_configs)
    plugins_dir = Path(__file__).parent.parent / "plugins"
    await plugins.load_plugins(plugins_dir)
    # Start the reminder scheduler in the background
    scheduler_task = asyncio.create_task(scheduler._scheduler_loop())
    logger.info("Scheduler task started")
    yield
    await plugins.stop_all_plugins()
    await mcp_client.stop_all()
    # Cancel the scheduler on shutdown
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await db.disconnect()


app = FastAPI(title="assistant-backend", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(device_tokens.router)
app.include_router(oauth_google.router)
