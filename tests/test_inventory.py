import json

import httpx
from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator

from skillbook.config import Settings
from skillbook.inventory import inventory


def test_inventory_validates_against_cyclonedx_schema():
    bom = inventory(Settings(_env_file=None))
    assert any(c["name"] == "skillbook" for c in bom["components"])
    assert not any(c["type"] == "machine-learning-model" for c in bom["components"])
    assert JsonStrictValidator(SchemaVersion.V1_6).validate_str(json.dumps(bom)) is None


def test_observed_model_is_labelled_as_reported_manifest(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "fixture-model",
                        "digest": "a" * 64,
                        "details": {"quantization_level": "Q4_K_M"},
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    bom = inventory(Settings(_env_file=None), observe_models=True)
    model = next(c for c in bom["components"] if c["type"] == "machine-learning-model")
    assert model["version"] == "a" * 64
    assert "weights-file" in str(model["properties"])
    assert JsonStrictValidator(SchemaVersion.V1_6).validate_str(json.dumps(bom)) is None
