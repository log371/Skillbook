import pytest
from pydantic import ValidationError

from skillbook.app import demo_release
from skillbook.domain import Proposal, Release
from skillbook.evaluation import CASES
from skillbook.policy import authorize


@pytest.mark.parametrize("name,proposal,expected", CASES, ids=[c[0] for c in CASES])
def test_boundary(name, proposal, expected):
    decision = authorize(demo_release(), "maintenance", proposal)
    assert decision.allowed is expected
    assert decision.document_id == ("maintenance" if expected else None)


def test_unknown_skill_cannot_grant_itself_permissions():
    decision = authorize(demo_release(), "admin", Proposal(tool="read_document"))
    assert decision.reason == "unknown_skill"


def test_manifest_requires_existing_document():
    payload = demo_release().model_dump()
    payload["skills"]["maintenance"]["document_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        Release.model_validate(payload)
