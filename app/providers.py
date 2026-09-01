"""Model provider registry — a flat, append-only list, Goose-style (see
docs/adr/009-tool-registry-and-progressive-disclosure.md — same philosophy
applied to model providers, not just tools).

Every provider is OpenAI-Chat-Completions-compatible (confirmed for each
before adding it here, not assumed), so the OpenAI SDK's own client works
against all of them via base_url + api_key — no per-provider client code.

Credentials load from env vars populated by
scripts/sync_secrets_from_bitwarden.sh (see docs/adr/011). A provider with
an unset env var simply won't appear in AVAILABLE_PROVIDERS — no crash, no
placeholder entry with an empty key.
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class ModelProvider:
    name: str
    base_url: str
    api_key_env: str
    default_model: str
    note: str = ""
    selectable: bool = True
    fetch_live: bool = False
    # Curated label for the default model; live variants derive one via
    # prettify_model_id. Clients fall back to their own derivation when empty.
    display_name: str = ""
    # Client-facing filter categories ("fast", "reasoning", "uncensored").
    tags: tuple[str, ...] = ()


def prettify_model_id(model_id: str) -> str:
    """Derive a display label from a raw model id ("org/some-model-2" -> "Some Model 2")."""
    part = model_id.rsplit("/", 1)[-1]
    return " ".join(
        word.capitalize() for word in part.replace("-", " ").replace("_", " ").split()
    )


# The shortlist. Every model id below was verified against the provider's
# live API on 2026-08-28.
PROVIDERS: list[ModelProvider] = [
    ModelProvider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_GEMINI_API_KEY",
        default_model="gemini-3.1-pro",
        note="Strongest pure-reasoning option, GA since Feb 2026.",
        fetch_live=True,
        display_name="Gemini 3.1 Pro",
        tags=("reasoning",),
    ),
    ModelProvider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        default_model="mistral-large-3",
        note="Flagship, Apache 2.0 open-weight.",
        fetch_live=True,
        display_name="Mistral Large 3",
        tags=("reasoning",),
    ),
    ModelProvider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-120b",
        note="Fastest inference of the shortlist — good for snappy chat.",
        fetch_live=True,
        display_name="GPT-OSS 120B (Groq)",
        tags=("fast",),
    ),
    ModelProvider(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-pro",
        note="Alternate flagship, different lab/training lineage than the rest.",
        fetch_live=True,
        display_name="DeepSeek V4 Pro",
        tags=("reasoning",),
    ),
    ModelProvider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="anthropic/claude-sonnet-4-6",
        note="Router, not a single model — flexible catch-all/fallback.",
        fetch_live=True,
        display_name="Claude Sonnet 4.6",
        tags=(),
    ),
    ModelProvider(
        name="hermes-3-405b",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="nousresearch/hermes-3-llama-3.1-405b",
        note="[Uncensored] Nous Research steerable frontier intelligence.",
        display_name="Hermes 3 (405B)",
        tags=("uncensored",),
    ),
    ModelProvider(
        name="dolphin-uncensored",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="cognitivecomputations/dolphin-mistral-24b-venice-edition",
        note="[Uncensored] Cognitive Computations conversational model without refusals.",
        display_name="Dolphin 2.9 (Venice)",
        tags=("uncensored",),
    ),
    ModelProvider(
        name="euryale-70b",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="sao10k/l3.3-euryale-70b",
        note="[Uncensored] Creative & expressive multi-turn conversational model.",
        display_name="L3.3 Euryale (70B)",
        tags=("uncensored",),
    ),
    ModelProvider(
        name="minimax",
        base_url="https://api.minimax.io/v1",
        api_key_env="MINIMAX_API_KEY",
        default_model="MiniMax-M3",
        note="Current general-purpose flagship, multimodal.",
        fetch_live=True,
        display_name="MiniMax M3",
        tags=("fast",),
    ),
    ModelProvider(
        name="mimo",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1",
        api_key_env="MIMO_API_KEY",
        default_model="mimo-lite",
        note="Xiaomi MiMo — item also has an anthropic_base_url field, unused here.",
        selectable=True,
        fetch_live=True,
        display_name="MiMo Lite",
        tags=(),
    ),
    ModelProvider(
        name="opencode-zen",
        base_url="https://opencode.ai",
        api_key_env="OPENCODE_API_KEY",
        default_model="deepseek-v4-flash-free",
        note=(
            "OpenCode's own gateway, 'OpenCode Zen'. Free tier has rotating "
            "models — treat default_model here as unstable, re-check periodically."
        ),
        selectable=False,
    ),
    ModelProvider(
        name="ollama",
        base_url="http://100.106.38.62:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        default_model="llama3.2:3b",
        note="Private local Ollama service over the Tailscale network.",
        selectable=True,
        fetch_live=True,
        display_name="Llama 3.2 3B (Ollama)",
        tags=(),
    ),
]


# Live catalog cache: provider name -> (fetched_at_monotonic, model_ids)
_live_cache: dict[str, tuple[float, list[str]]] = {}
_LIVE_CACHE_TTL_S = 3600  # 1 hour


async def fetch_live_model_ids(provider: ModelProvider) -> list[str] | None:
    """Try to list models from provider's OpenAI-compatible /v1/models.

    Returns None on any failure (auth, network, non-OpenAI shape) so caller
    falls back to the static default_model.
    """
    import time as _time

    import httpx

    cached = _live_cache.get(provider.name)
    if cached is not None:
        fetched_at, ids = cached
        if _time.monotonic() - fetched_at < _LIVE_CACHE_TTL_S:
            return ids

    key = os.environ.get(provider.api_key_env)
    if not key:
        return None

    headers = {"Authorization": f"Bearer {key}"}
    # Gemini's OpenAI-compat base already includes /v1beta/openai — its list
    # endpoint is still /v1beta/openai/models per Google docs. Normalising
    # to base_url + "/models" works for all current providers.
    url = provider.base_url.rstrip("/") + "/models"

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
            # OpenAI shape: {"data": [{"id": "..."}, ...]} — some providers
            # use {"models": [...]} or bare list; handle all three.
            raw: list[dict] | None = None
            if isinstance(data, dict) and "data" in data:
                raw = data["data"]
            elif isinstance(data, dict) and "models" in data:
                raw = data["models"]
            elif isinstance(data, list):
                raw = data  # type: ignore[assignment]
            if not raw:
                return None
            ids = [str(item.get("id") or item.get("name") or "") for item in raw if isinstance(item, dict)]
            ids = [i for i in ids if i]
            if not ids:
                return None
            _live_cache[provider.name] = (_time.monotonic(), ids)
            return ids
    except Exception:
        return None


async def all_models_for_provider(provider: ModelProvider) -> list[str]:
    """Live-verified list when fetch_live is set, otherwise static default.

    When live fetch succeeds, ONLY live IDs are returned (capped) — every
    choice the API advertises is therefore live. The static default is kept
    at the front only if the live catalog actually contains it.
    """
    if not provider.fetch_live:
        return [provider.default_model]
    live = await fetch_live_model_ids(provider)
    if not live:
        return [provider.default_model]
    # Promote default to front if it is live; otherwise trust the live list as-is.
    if provider.default_model in live:
        live = [provider.default_model] + [m for m in live if m != provider.default_model]
    # Cap to keep the picker usable — OpenRouter alone advertises 300+.
    return live[:30]

def available_providers() -> list[ModelProvider]:
    """Providers whose API key is actually set in the environment."""
    return [p for p in PROVIDERS if os.environ.get(p.api_key_env)]


def selectable_providers() -> list[ModelProvider]:
    return [provider for provider in available_providers() if provider.selectable]


def get_provider(name: str) -> ModelProvider | None:
    return next((p for p in available_providers() if p.name == name), None)
