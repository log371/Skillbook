import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from skillbook.app import create_app, demo_release
from skillbook.config import Settings
from skillbook.domain import Proposal
from skillbook.provider import ProviderError
from skillbook.releases import ReleaseStore, sign

TOKEN = "test-only-random-looking-token-not-for-deployment-123456"
HEADERS = {"Authorization": "Bearer " + TOKEN}
REQUEST = {"question": "Consulte le contrat de maintenance."}


def settings(tmp_path, **kwargs):
    return Settings(
        _env_file=None, api_key=TOKEN, provider="mock", audit_db=tmp_path / "audit.sqlite", **kwargs
    )


class MaliciousProvider:
    async def propose(self, request, skill):
        return Proposal(tool="read_document", arguments={"document_id": "restricted"})


def test_auth_and_happy_path(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/v1/run", json=REQUEST).status_code == 401
        assert (
            client.get("/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
        result = client.post("/v1/run", headers=HEADERS, json=REQUEST).json()
        assert result["decision"]["allowed"] is True
        assert "ThermoSud" in result["content"]
        assert result["provider"] == "mock"
        assert client.get("/v1/status", headers=HEADERS).json()["release_mode"] == "builtin-demo"


def test_malicious_model_cannot_read_out_of_scope_and_logs_are_redacted(tmp_path):
    config = settings(tmp_path)
    with TestClient(create_app(config, MaliciousProvider())) as client:
        response = client.post(
            "/v1/run",
            headers=HEADERS,
            json={
                **REQUEST,
                "context": "USER-SECRET-NEVER-LOG-THIS",
            },
        )
        assert response.status_code == 200
        assert response.json()["decision"]["reason"] == "scope_denied"
        assert response.json()["content"] is None
        assert "CANARY" not in response.text
    with closing(sqlite3.connect(config.audit_db)) as db:
        events = str(db.execute("SELECT payload FROM events").fetchall())
    assert "scope_denied" in events
    assert "USER-SECRET" not in events
    assert TOKEN not in events


def test_validation_and_unknown_skill(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert (
            client.post(
                "/v1/run",
                headers=HEADERS,
                json={
                    **REQUEST,
                    "skill_id": "missing",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/run",
                headers=HEADERS,
                json={
                    **REQUEST,
                    "tool": "shell",
                },
            ).status_code
            == 422
        )
        assert client.post("/v1/run", headers=HEADERS, content=b"x" * 50000).status_code == 413
        assert (
            client.post(
                "/v1/run",
                headers=HEADERS,
                json={
                    **REQUEST,
                    "context": "x" * 8001,
                },
            ).status_code
            == 422
        )


def test_missing_key_refuses_startup(tmp_path):
    config = settings(tmp_path).model_copy(update={"api_key": Settings(_env_file=None).api_key})
    with pytest.raises(ValueError, match="API_KEY"), TestClient(create_app(config)):
        pass


def test_provider_error_and_audit_failure_are_closed(tmp_path, monkeypatch):
    class BrokenProvider:
        async def propose(self, request, skill):
            raise ProviderError("do not leak internal details")

    app = create_app(settings(tmp_path), BrokenProvider())
    with TestClient(app) as client:
        response = client.post("/v1/run", headers=HEADERS, json=REQUEST)
        assert response.status_code == 502
        assert "do not leak" not in response.text

        def disk_full(*args, **kwargs):
            raise OSError("full")

        monkeypatch.setattr(app.state.audit, "append", disk_full)
        assert client.post("/v1/run", headers=HEADERS, json=REQUEST).status_code == 503


def test_busy_and_timeout(tmp_path):
    class SlowProvider:
        async def propose(self, request, skill):
            await asyncio.sleep(2)

    app = create_app(settings(tmp_path, timeout_seconds=1), SlowProvider())
    with TestClient(app) as client:
        app.state.busy = True
        assert client.post("/v1/run", headers=HEADERS, json=REQUEST).status_code == 429
        app.state.busy = False
        assert client.post("/v1/run", headers=HEADERS, json=REQUEST).status_code == 502
        assert app.state.busy is False


def test_signed_release_is_used_by_api(tmp_path):
    key = Ed25519PrivateKey.generate()
    pub = tmp_path / "trusted.pub"
    pub.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    store = ReleaseStore(tmp_path / "releases", key.public_key())
    release = demo_release().model_copy(update={"version": 2})
    release.documents["maintenance"] = "Updated signed contract"
    state = store.activate(sign(release, key))
    app = create_app(settings(tmp_path, release_state=str(store.directory), trusted_key=str(pub)))
    with TestClient(app) as client:
        result = client.post("/v1/run", headers=HEADERS, json=REQUEST).json()
        assert result["release_version"] == 2
        assert result["content"] == "Updated signed contract"
    installed = store.directory / "releases" / (state["active"] + ".json")
    installed.write_bytes(b"tampered")
    with pytest.raises(ValueError), TestClient(app):
        pass


@pytest.mark.parametrize(
    "url", ["https://example.com", "http://localhost@evil.test", "http://localhost/x"]
)
def test_external_model_endpoints_rejected(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, ollama_url=url)


def test_partial_release_config_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, release_state=str(Path("state")))
