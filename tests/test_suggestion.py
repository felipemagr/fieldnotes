import pytest

from fieldnotes.domain.suggestion import parse_suggestion

GOOD = '{"client_needs": ["Excel tape"], "fence_mapping": [{"need": "tape", "approach": "adapter", "endpoint": "POST /v2/declarations", "doc_ref": null}], "questions_to_ask": [], "route_to_ops": [], "risks": []}'


def test_plain_json():
    s = parse_suggestion(GOOD)
    assert s.client_needs == ["Excel tape"]
    assert s.fence_mapping[0].endpoint == "POST /v2/declarations"


def test_prose_wrapped():
    assert parse_suggestion(f"Sure! Here it is: {GOOD} Let me know.").client_needs


def test_code_fence():
    assert parse_suggestion(f"```json\n{GOOD}\n```").fence_mapping[0].need == "tape"


def test_missing_lists_default_to_empty():
    s = parse_suggestion('{"client_needs": ["x"]}')
    assert s.risks == [] and s.answered_questions == []


@pytest.mark.parametrize("broken", ["no json here", '{"client_needs": ["x"', "{not json}", ""])
def test_broken_raises_value_error(broken):
    with pytest.raises(ValueError):  # pydantic's ValidationError is a ValueError
        parse_suggestion(broken)


def test_wrong_types_raise():
    with pytest.raises(ValueError):
        parse_suggestion('{"client_needs": "not a list"}')
