"""FastAPI application entry point.

Run locally: uvicorn app.main:app --reload
Run in production: see assistant.service (systemd unit shipped in phase 00).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from . import db, scheduler
from .routers import chat, device_tokens, health, memory, models, oauth_google, threads
from .tools import calendar as calendar_tools  # noqa: F401  registers calendar tools
from .tools import gmail as gmail_tools  # noqa: F401  registers gmail tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.connect()
    # Start the reminder scheduler in the background
    scheduler_task = asyncio.create_task(scheduler._scheduler_loop())
    logger.info("Scheduler task started")
    yield
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
app.include_router(models.router)
app.include_router(threads.router)
app.include_router(memory.router)
