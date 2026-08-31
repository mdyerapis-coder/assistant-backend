"""Thin wrapper around the OpenAI SDK's async client.

Points at app/providers.py's "minimax" entry, not Cline's gateway (the
original plan) — Cline's account has a negative credit balance as of
2026-08-27 (confirmed by hitting api.cline.bot directly: every model
returns insufficient_credits or model-not-found), so this backend is
unusable until that's topped up. See
phases/01_chat-loop/REPORT.md. Swapping the active provider is just
changing _ACTIVE_PROVIDER_NAME below until real per-request provider
selection is built (that's still a later concern than proving the loop
works — see app/providers.py's module docstring).
"""

import os

from openai import AsyncOpenAI

from . import providers

_ACTIVE_PROVIDER_NAME = "minimax"
_active = providers.get_provider(_ACTIVE_PROVIDER_NAME)

if _active is not None:
    DEFAULT_MODEL = _active.default_model
    _api_key = os.environ[_active.api_key_env]
    _base_url = _active.base_url
    # MiniMax-specific: its OpenAI-compatible endpoint defaults to inlining
    # <think>...</think> chain-of-thought straight into `content` (confirmed
    # live 2026-08-27 — leaks into the SSE delta stream otherwise, which
    # docs/CONTRACT.md has no event type for). Disabling it outright is
    # simpler than adding a reasoning-content event just for one provider;
    # revisit if/when real per-provider config lands.
    EXTRA_BODY: dict = (
        {"thinking": {"type": "disabled"}} if _ACTIVE_PROVIDER_NAME == "minimax" else {}
    )
else:
    # dev/test fallback: no real provider key set in this environment (e.g.
    # local pytest runs). Every call site here either monkeypatches
    # `create` directly or never reaches the network, so this placeholder
    # value itself is never actually used — it only needs to let the SDK
    # construct without erroring (it now refuses an empty-string key).
    DEFAULT_MODEL = "unset"
    _api_key = "unset"
    _base_url = None
    EXTRA_BODY = {}
client = AsyncOpenAI(api_key=_api_key, base_url=_base_url)


# Public mirror of _ACTIVE_PROVIDER_NAME for /v1/models (the id the app
# sends back as the chat request's `model` field when nothing is selected).
ACTIVE_PROVIDER_NAME = _ACTIVE_PROVIDER_NAME

_clients_by_provider: dict[str, AsyncOpenAI] = {}


def resolve(model_id: str | None) -> tuple[AsyncOpenAI, str, dict]:
    """Map the chat request's optional `model` id (a provider name from
    /v1/models) to a client + model + extra_body. Unknown or missing ids
    fall back to the active provider — never an error path, the phone's
    saved selection shouldn't hard-fail a chat because a provider key was
    rotated out (phase 05 contract repair)."""
    provider = providers.get_provider(model_id) if model_id else None
    if provider is None:
        return client, DEFAULT_MODEL, EXTRA_BODY
    resolved = _clients_by_provider.setdefault(
        provider.name,
        AsyncOpenAI(
            api_key=os.environ[provider.api_key_env], base_url=provider.base_url
        ),
    )
    extra = {"thinking": {"type": "disabled"}} if provider.name == "minimax" else {}
    return resolved, provider.default_model, extra
