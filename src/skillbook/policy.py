from pydantic import ValidationError

from skillbook.domain import Decision, Proposal, ReadArguments, Release


def authorize(release: Release, skill_id: str, proposal: Proposal) -> Decision:
    """No LLM verdict, regex detector or skill prose can grant a capability."""
    skill = release.skills.get(skill_id)
    if skill is None:
        return Decision(allowed=False, reason="unknown_skill")
    if proposal.tool != "read_document":
        return Decision(allowed=False, reason="unknown_tool")
    try:
        args = ReadArguments.model_validate(proposal.arguments)
    except ValidationError:
        return Decision(allowed=False, reason="invalid_arguments")
    if args.document_id not in skill.document_ids:
        return Decision(allowed=False, reason="scope_denied")
    return Decision(allowed=True, reason="allowed", document_id=args.document_id)
