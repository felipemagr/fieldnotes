from fieldnotes.domain.trigger import TurnTrigger, is_question
from fieldnotes.domain.turn import Turn


def turn(speaker, text):
    return Turn(speaker=speaker, text=text, t0=0, t1=1)


LONG = "our loan tape is an excel export that we cannot change because the vendor owns the format"


def test_long_client_turn_fires():
    t = TurnTrigger(min_words=15)
    t.add(turn("client", LONG))
    assert [x.text for x in t.take(now=0, busy=False)] == [LONG]


def test_short_client_turn_waits():
    t = TurnTrigger(min_words=15)
    t.add(turn("client", "yes, monthly"))
    assert t.take(now=0, busy=False) is None


def test_client_question_fires_even_if_short():
    t = TurnTrigger(min_words=15)
    t.add(turn("client", "Can we get a higher advance rate?"))
    assert t.take(now=0, busy=False)


def test_my_turns_never_fire_but_ride_along():
    t = TurnTrigger(min_words=3)
    t.add(turn("me", "How do you send the file today? Tell me everything"))
    assert t.take(now=0, busy=False) is None
    t.add(turn("client", LONG))
    batch = t.take(now=0, busy=False)
    assert [x.speaker for x in batch] == ["me", "client"]


def test_busy_coalesces_turns_into_one_batch():
    t = TurnTrigger(min_words=3, debounce_s=0)
    t.add(turn("client", LONG))
    assert t.take(now=0, busy=True) is None
    t.add(turn("client", "and repayments come through stripe webhooks"))
    batch = t.take(now=1, busy=False)
    assert len(batch) == 2
    assert t.take(now=2, busy=False) is None


def test_debounce_spaces_requests():
    t = TurnTrigger(min_words=3, debounce_s=2)
    t.add(turn("client", LONG))
    assert t.take(now=10, busy=False)
    t.add(turn("client", LONG))
    assert t.take(now=11, busy=False) is None
    assert t.wait_s(11) == 1
    assert t.take(now=12, busy=False)


def test_drain_returns_everything():
    t = TurnTrigger()
    t.add(turn("client", "ok"))
    assert len(t.drain()) == 1 and not t.armed


def test_is_question():
    assert is_question("what time zone do you use")
    assert is_question("that is the file?")
    assert not is_question("we send it monthly")
