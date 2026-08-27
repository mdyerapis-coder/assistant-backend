"""FastAPI application entry point.

Run locally: uvicorn app.main:app --reload
Run in production: see assistant.service (systemd unit shipped in phase 00).
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from . import db
from .routers import chat, health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="assistant-backend", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router)
