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
        assert body["default_model_id"] == openai_client.ACTIVE_PROVIDER_NAME
        assert body["models"] == [
            {
                "id": "testprov",
                "model": "test-1",
                "provider": "testprov",
                "description": "for tests",
            }
        ]


def test_models_catalog_hides_providers_without_keys(monkeypatch):
    monkeypatch.delenv("TESTPROV_API_KEY", raising=False)
    monkeypatch.setattr(providers, "PROVIDERS", [TEST_PROVIDER])
    with TestClient(app) as client:
        body = client.get("/v1/models", headers=HEADERS).json()
        assert body["models"] == []


def test_resolve_returns_requested_provider_client(monkeypatch):
    monkeypatch.setenv("TESTPROV_API_KEY", "key")
    monkeypatch.setattr(providers, "PROVIDERS", [TEST_PROVIDER])
    resolved_client, model, extra = openai_client.resolve("testprov")
    assert model == "test-1"
    assert extra == {}
    assert resolved_client is not openai_client.client
    # same provider resolves to the same cached client
    again, _, _ = openai_client.resolve("testprov")
    assert again is resolved_client


def test_resolve_falls_back_to_active_provider_on_unknown_id():
    resolved_client, model, extra = openai_client.resolve("no-such-provider")
    assert resolved_client is openai_client.client
    assert model == openai_client.DEFAULT_MODEL
    assert extra == openai_client.EXTRA_BODY


def test_resolve_falls_back_when_model_omitted():
    resolved_client, _, _ = openai_client.resolve(None)
    assert resolved_client is openai_client.client
