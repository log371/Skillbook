import asyncio

import pytest

from skillbook.config import Settings
from skillbook.domain import Proposal
from skillbook.evaluation import evaluate_model
from skillbook.provider import Provider, ProviderError


def test_live_report_distinguishes_provider_errors(monkeypatch):
    async def propose(self, request, skill):
        if "http_post" in request.context:
            raise ProviderError("unavailable")
        return Proposal(tool="read_document", arguments={"document_id": "restricted"})

    monkeypatch.setattr(Provider, "propose", propose)
    report = asyncio.run(evaluate_model(Settings(_env_file=None, provider="ollama")))
    assert len(report["cases"]) == 6
    assert report["errors"] == 1
    assert all(not c["decision"]["allowed"] for c in report["cases"] if not c["provider_error"])


def test_live_refuses_mock():
    with pytest.raises(ValueError):
        asyncio.run(evaluate_model(Settings(_env_file=None, provider="mock")))
