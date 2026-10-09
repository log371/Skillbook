import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Skill(StrictModel):
    instructions: str = Field(min_length=1, max_length=4000)
    document_ids: list[Identifier] = Field(min_length=1, max_length=20)


class Release(StrictModel):
    schema_version: Literal[1] = 1
    version: int = Field(ge=1)
    documents: dict[Identifier, Annotated[str, Field(min_length=1, max_length=16000)]] = Field(
        min_length=1, max_length=50
    )
    skills: dict[Identifier, Skill] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def references_exist(self):
        for skill in self.skills.values():
            if not set(skill.document_ids) <= self.documents.keys():
                raise ValueError("Skill references missing documents")
        return self


class Proposal(StrictModel):
    # Unknown tool names are deliberately representable: the policy must reject them.
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict, max_length=8)


class ReadArguments(StrictModel):
    document_id: Identifier


class RunRequest(StrictModel):
    skill_id: Identifier = "maintenance"
    question: str = Field(min_length=3, max_length=2000)
    context: str = Field(default="", max_length=8000)


class Decision(StrictModel):
    allowed: bool
    reason: Literal["allowed", "unknown_skill", "unknown_tool", "invalid_arguments", "scope_denied"]
    document_id: str | None = None


class RunResult(StrictModel):
    request_id: str
    release_version: int
    release_sha256: str
    provider: str
    decision: Decision
    content: str | None = None
