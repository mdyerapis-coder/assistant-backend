import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from fastapi.testclient import TestClient

from app import openai_client, providers
from app.main import app
from app.providers import ModelProvider

HEADERS = {"Authorization": "Bearer test-token"}

TEST_PROVIDER = ModelProvider(
    name="testprov",
    base_url="http://localhost:1",
    api_key_env="TESTPROV_API_KEY",
    default_model="test-1",
    note="for tests",
)


def test_models_requires_auth():
    with TestClient(app) as client:
        assert client.get("/v1/models").status_code == 401


def test_models_catalog_lists_configured_providers(monkeypatch):
    monkeypatch.setenv("TESTPROV_API_KEY", "key")
    monkeypatch.setattr(providers, "PROVIDERS", [TEST_PROVIDER])
    with TestClient(app) as client:
        resp = client.get("/v1/models", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["models"] == [
            {
                "id": "testprov",
                "model": "test-1",
                "provider": "testprov",
                "description": "for tests",
                "display_name": "Test 1",
                "tags": [],
            }
        ]
        # active provider (minimax) has no key in this env, so the sole
        # configured provider becomes the advertised default
        assert body["default_model_id"] == "testprov"


def test_models_catalog_empty_without_any_keys(monkeypatch):
    monkeypatch.delenv("TESTPROV_API_KEY", raising=False)
    monkeypatch.setattr(providers, "PROVIDERS", [TEST_PROVIDER])
    with TestClient(app) as client:
        body = client.get("/v1/models", headers=HEADERS).json()
        assert body["models"] == []
        assert body["default_model_id"] is None


def test_resolve_model_returns_runtime_for_configured_provider(monkeypatch):
    monkeypatch.setenv("TESTPROV_API_KEY", "key")
    monkeypatch.setattr(providers, "PROVIDERS", [TEST_PROVIDER])
    runtime = openai_client.resolve_model("testprov")
    assert runtime is not None
    assert runtime.model == "test-1"
    assert runtime.extra_body == {}
    assert runtime.client is not openai_client.client


def test_resolve_model_defaults_when_model_omitted():
    runtime = openai_client.resolve_model(None)
    assert runtime is not None
    assert runtime.client is openai_client.client
    assert runtime.model == openai_client.DEFAULT_MODEL


def test_resolve_model_rejects_unknown_id():
    assert openai_client.resolve_model("no-such-provider") is None


def test_chat_rejects_unknown_model_with_422():
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat", headers=HEADERS, json={"message": "hi", "model": "nope"}
        )
        assert resp.status_code == 422


def test_providers_requires_auth():
    with TestClient(app) as client:
        assert client.get("/v1/providers").status_code == 401


def test_providers_list_configuration_status(monkeypatch):
    """Operator visibility: full registry, configured flag per provider, no secrets."""
    configured = ModelProvider(
        name="cfg",
        base_url="http://localhost:1",
        api_key_env="CFG_TEST_KEY",
        default_model="cfg-1",
        note="ready to go",
        selectable=True,
    )
    unconfigured = ModelProvider(
        name="nocfg",
        base_url="http://localhost:2",
        api_key_env="NOCFG_TEST_KEY",
        default_model="no-1",
        note="missing key",
        selectable=False,
    )
    monkeypatch.setenv("CFG_TEST_KEY", "present")
    monkeypatch.delenv("NOCFG_TEST_KEY", raising=False)
    monkeypatch.setattr(providers, "PROVIDERS", [configured, unconfigured])

    with TestClient(app) as client:
        resp = client.get("/v1/providers", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()["providers"]

    by_name = {p["name"]: p for p in body}
    assert by_name["cfg"] == {
        "name": "cfg",
        "default_model": "cfg-1",
        "note": "ready to go",
        "configured": True,
        "selectable": True,
    }
    assert by_name["nocfg"]["configured"] is False
    assert by_name["nocfg"]["selectable"] is False


def test_models_carry_display_name_and_tags(monkeypatch):
    provider = ModelProvider(
        name="testprov",
        base_url="http://localhost:1",
        api_key_env="TESTPROV_API_KEY",
        default_model="test-1",
        note="for tests",
        display_name="Test One",
        tags=("fast",),
    )
    monkeypatch.setenv("TESTPROV_API_KEY", "key")
    monkeypatch.setattr(providers, "PROVIDERS", [provider])
    with TestClient(app) as client:
        body = client.get("/v1/models", headers=HEADERS).json()
    entry = body["models"][0]
    assert entry["display_name"] == "Test One"
    assert entry["tags"] == ["fast"]


def test_live_models_derive_display_names_and_inherit_tags(monkeypatch):
    provider = ModelProvider(
        name="testprov",
        base_url="http://localhost:1",
        api_key_env="TESTPROV_API_KEY",
        default_model="test-1",
        note="for tests",
        fetch_live=True,
        display_name="Test One",
        tags=("reasoning",),
    )

    async def fake_live(p):
        return ["test-1", "testprov/test-2-mini"]

    monkeypatch.setenv("TESTPROV_API_KEY", "key")
    monkeypatch.setattr(providers, "PROVIDERS", [provider])
    monkeypatch.setattr(providers, "all_models_for_provider", fake_live)
    with TestClient(app) as client:
        body = client.get("/v1/models", headers=HEADERS).json()
    entries = body["models"]
    assert [e["id"] for e in entries] == [
        "testprov:test-1",
        "testprov:testprov/test-2-mini",
    ]
    # default model keeps the curated name; other live variants derive one
    assert entries[0]["display_name"] == "Test One"
    assert entries[1]["display_name"] == "Test 2 Mini"
    assert all(e["tags"] == ["reasoning"] for e in entries)
