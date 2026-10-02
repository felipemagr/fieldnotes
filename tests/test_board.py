from fieldnotes.domain.board import Board, similar
from fieldnotes.domain.suggestion import Mapping, Suggestion


def test_similar():
    assert similar("What does a blank DPD mean?", "what does a blank DPD mean")
    assert similar("Which column is the loan id?", "Which column is the loan ID")
    assert not similar("Who gets the alert when a file fails?", "What time zone do you use?")


def test_merge_dedupes_and_marks_new():
    b = Board()
    b.merge(Suggestion(questions_to_ask=["What does a blank DPD mean?"], risks=["Blank DPD"]))
    changed = b.merge(Suggestion(questions_to_ask=["What does a blank DPD mean", "Time zone?"]))
    assert [i.text for i in changed] == ["Time zone?"]
    snap = b.snapshot()["sections"]["ask"]
    assert [i["text"] for i in snap] == [
        "Time zone?",
        "What does a blank DPD mean?",
    ]  # newest first
    assert [i["new"] for i in snap] == [True, False]


def test_dismissed_never_comes_back():
    b = Board()
    (item,) = b.merge(Suggestion(risks=["Presigned URLs expire after 1 hour"]))
    b.dismiss(item.id)
    assert b.merge(Suggestion(risks=["Presigned URLs expire after 1 hour."])) == []
    assert b.visible("risks") == []


def test_pinned_stays_on_top():
    b = Board()
    (old,) = b.merge(Suggestion(client_needs=["Excel tape"]))
    b.merge(Suggestion(client_needs=["Stripe repayments"]))
    b.pin(old.id)
    assert [i.text for i in b.visible("needs")] == ["Excel tape", "Stripe repayments"]


def test_mapping_gains_endpoint_later():
    b = Board()
    b.merge(Suggestion(fence_mapping=[Mapping(need="Validate first", approach="ask")]))
    changed = b.merge(
        Suggestion(
            fence_mapping=[
                Mapping(need="Validate first", approach="dry_run", endpoint="POST /v2/declarations")
            ]
        )
    )
    assert changed[0].endpoint == "POST /v2/declarations"
    assert len(b.visible("mapping")) == 1


def test_answered_questions_leave_the_board():
    b = Board()
    b.merge(Suggestion(questions_to_ask=["How often do you send the file?", "Time zone?"]))
    b.merge(Suggestion(answered_questions=["How often do you send the file?"]))
    assert b.open_questions() == ["Time zone?"]
    assert "How often do you send the file?" in b.as_text()


def test_short_item_does_not_swallow_a_specific_one():
    b = Board()
    b.merge(Suggestion(questions_to_ask=["Time zones?"]))
    b.merge(Suggestion(questions_to_ask=["Is month end in Madrid time or UTC?"]))
    assert len(b.open_questions()) == 2


def test_rephrased_question_is_a_duplicate():
    assert similar(
        "Which columns are loan ID, principal amount, fees, due date, status?",
        "Which fields in the Excel describe principal, fees, due date, status?",
    )
    assert similar(
        "Does Excel include borrower state and country per row?",
        "Does the Excel have borrower state and country for each loan?",
    )
    assert not similar("Time zones?", "Is month end in Madrid time or UTC?")
    assert not similar("Who gets the alert when a file fails?", "Can you send a sample file?")


def test_brief_lists_the_board_for_the_model():
    b = Board()
    b.merge(Suggestion(client_needs=["Excel tape"], questions_to_ask=["Sample file?"]))
    assert b.brief() == "client_needs: Excel tape\nquestions_to_ask (open): Sample file?"
