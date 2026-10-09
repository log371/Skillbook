from datetime import UTC, datetime
from importlib.metadata import distributions
from uuid import uuid4

import httpx

from skillbook import __version__
from skillbook.config import Settings


def inventory(settings: Settings, observe_models: bool = False) -> dict:
    components = []
    for dist in sorted(distributions(), key=lambda item: item.metadata["Name"].lower()):
        name, version = dist.metadata["Name"], dist.version
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "bom-ref": f"python:{name.lower()}:{version}",
                "properties": [
                    {"name": "skillbook:evidence", "value": "installed-package-metadata"}
                ],
            }
        )
    if observe_models:
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.get(settings.ollama_url + "/api/tags")
            response.raise_for_status()
        for model in response.json()["models"]:
            components.append(
                {
                    "type": "machine-learning-model",
                    "name": model["name"],
                    "version": model["digest"],
                    "bom-ref": "ollama:" + model["digest"],
                    "properties": [
                        {"name": "skillbook:manifest-digest", "value": model["digest"]},
                        {
                            "name": "skillbook:quantization",
                            "value": model.get("details", {}).get("quantization_level", "unknown"),
                        },
                        {
                            "name": "skillbook:evidence",
                            "value": "ollama-api-tags; not a weights-file hash",
                        },
                        {
                            "name": "skillbook:license",
                            "value": "unknown; verify upstream model license",
                        },
                    ],
                }
            )
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "serialNumber": "urn:uuid:" + str(uuid4()),
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {"type": "application", "name": "skillbook", "version": __version__},
            "properties": [
                {
                    "name": "skillbook:scope",
                    "value": "current Python environment (including dev tools)",
                },
                {"name": "skillbook:models-observed", "value": str(observe_models).lower()},
                {
                    "name": "skillbook:limitations",
                    "value": "No OS/image SBOM, training data or CVE assessment",
                },
            ],
        },
        "components": components,
    }
