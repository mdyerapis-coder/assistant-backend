import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_requires_bearer_token():
    resp = client.get("/v1/health")
    assert resp.status_code == 401


def test_health_rejects_wrong_token():
    resp = client.get("/v1/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_health_ok_with_correct_token():
    resp = client.get("/v1/health", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
