"""GET /v1/health — bearer-gated cheap ping.

Used both by the Android app's onboarding "verify token" step and as a
deploy smoke test. See phases/00_backend-skeleton/CONTEXT.md's human-check.
"""

from fastapi import APIRouter, Depends

from ..auth import require_bearer_token

router = APIRouter()


@router.get("/v1/health", dependencies=[Depends(require_bearer_token)])
async def health() -> dict[str, str]:
    return {"status": "ok"}
