"""FastAPI application entry point.

Run locally: uvicorn app.main:app --reload
Run in production: see assistant.service (systemd unit shipped in phase 00).
"""

from fastapi import FastAPI

from .routers import health

app = FastAPI(title="assistant-backend")
app.include_router(health.router)
