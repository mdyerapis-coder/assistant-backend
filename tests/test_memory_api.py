import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from fastapi.testclient import TestClient

from app.main import app

HEADERS = {"Authorization": "Bearer test-token"}


def test_memory_requires_auth():
    with TestClient(app) as client:
        assert client.get("/v1/memory").status_code == 401


def test_get_memory_empty():
    with TestClient(app) as client:
        resp = client.get("/v1/memory", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"facts": []}


def test_patch_memory_upserts_and_returns_facts():
    with TestClient(app) as client:
        resp = client.patch(
            "/v1/memory",
            headers=HEADERS,
            json={"facts": {"timezone": "Australia/Sydney", "dog_name": "Rover"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rejected"] == []
        assert [f["key"] for f in body["facts"]] == ["dog_name", "timezone"]
        assert body["facts"][1]["value"] == "Australia/Sydney"
        assert body["facts"][1]["updated_at"]

        # and GET reflects the same state
        get = client.get("/v1/memory", headers=HEADERS).json()
        assert [f["key"] for f in get["facts"]] == ["dog_name", "timezone"]


def test_patch_memory_overwrites_existing_value():
    with TestClient(app) as client:
        client.patch(
            "/v1/memory", headers=HEADERS, json={"facts": {"timezone": "UTC"}}
        )
        resp = client.patch(
            "/v1/memory",
            headers=HEADERS,
            json={"facts": {"timezone": "Australia/Sydney"}},
        )
        facts = {f["key"]: f["value"] for f in resp.json()["facts"]}
        assert facts == {"timezone": "Australia/Sydney"}


def test_patch_memory_null_value_deletes_key():
    with TestClient(app) as client:
        client.patch(
            "/v1/memory", headers=HEADERS, json={"facts": {"stale": "no longer true"}}
        )
        resp = client.patch(
            "/v1/memory", headers=HEADERS, json={"facts": {"stale": None}}
        )
        assert resp.json()["facts"] == []


def test_patch_memory_reports_cap_rejections_without_storing():
    with TestClient(app) as client:
        giant = "y" * 5000
        resp = client.patch(
            "/v1/memory", headers=HEADERS, json={"facts": {"giant": giant}}
        )
        body = resp.json()
        assert body["facts"] == []
        assert len(body["rejected"]) == 1
        assert body["rejected"][0]["key"] == "giant"
        assert "cap" in body["rejected"][0]["reason"].lower()
