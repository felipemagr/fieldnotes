"""What the Brain returns after each batch of turns, and how its answer is read."""

from pydantic import BaseModel, Field


class Mapping(BaseModel):
    need: str  # what the client needs, in their words
    approach: str  # how to do it on the platform
    endpoint: str | None = None  # exact endpoint from the docs, or None
    doc_ref: str | None = None  # docs page/section it came from
    unverified: list[str] = []  # field names the docs never mention (set in code)


class Suggestion(BaseModel):
    client_needs: list[str] = Field(default_factory=list)
    fence_mapping: list[Mapping] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)  # gaps not answered yet
    route_to_ops: list[str] = Field(default_factory=list)  # contract meaning, commercial
    risks: list[str] = Field(default_factory=list)  # data quality, timing, idempotency, security
    # Open questions from earlier updates that the client has now answered, verbatim.
    answered_questions: list[str] = Field(default_factory=list)


def extract_json(text: str) -> str:
    """The text from the first `{` to the last `}`.

    Models wrap the object in a code fence or prose even when told not to.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object in the answer: {text.strip()[:120]!r}")
    return text[start : end + 1]


def parse_suggestion(text: str) -> Suggestion:
    """Read a Suggestion out of a model answer. Raises ValueError when it is not one."""
    return Suggestion.model_validate_json(extract_json(text))
