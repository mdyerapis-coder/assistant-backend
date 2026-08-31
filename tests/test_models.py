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
