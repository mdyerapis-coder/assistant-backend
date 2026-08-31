"""GET /v1/models — the provider catalog (phase 05, contract repair).

The Android app's model picker (assistant-android phase 04) has called
GET /v1/models since it landed, but no backend route existed — the picker
404'd against the live backend and the `model` field it sent with each
chat request was silently ignored. This endpoint closes that gap using
the existing providers registry: one entry per provider whose API key is
actually configured. Contract: docs/CONTRACT.md.
"""

from fastapi import APIRouter, Depends

from .. import openai_client, providers
from ..auth import require_bearer_token

router = APIRouter(dependencies=[Depends(require_bearer_token)])


@router.get("/v1/models")
async def list_models() -> dict:
    available = providers.available_providers()
    return {
        # The provider chat requests go to when the request carries no
        # `model` field — see openai_client.resolve().
        "default_model_id": openai_client.ACTIVE_PROVIDER_NAME,
        "models": [
            {
                "id": p.name,
                "model": p.default_model,
                "provider": p.name,
                "description": p.note,
            }
            for p in available
        ],
    }
