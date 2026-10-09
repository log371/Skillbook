import asyncio
import json

import httpx
import pytest

from skillbook.app import demo_release
from skillbook.config import Settings
from skillbook.domain import RunRequest
from skillbook.provider import Provider, ProviderError


@pytest.mark.parametrize("mode", ["ok", "bad_json", "oversized", "redirect", "error"])
def test_ollama_protocol_and_failures(monkeypatch, mode):
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["messages"][0]["role"] == "system"
        assert "untrusted_context" in body["messages"][1]["content"]
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid"})
        if mode == "error":
            return httpx.Response(500)
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 70000)
        content = (
            "not json"
            if mode == "bad_json"
            else json.dumps(
                {
                    "tool": "read_document",
                    "arguments": {"document_id": "maintenance"},
                }
            )
        )
        return httpx.Response(200, json={"message": {"content": content}})

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = Provider(Settings(_env_file=None, provider="ollama"))
    task = provider.propose(
        RunRequest(question="Read maintenance"), demo_release().skills["maintenance"]
    )
    if mode == "ok":
        assert asyncio.run(task).arguments["document_id"] == "maintenance"
    else:
        with pytest.raises(ProviderError):
            asyncio.run(task)
