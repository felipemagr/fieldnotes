from fieldnotes.adapters.live import EchoGuard


def test_mic_speech_during_client_speech_is_echo():
    guard = EchoGuard()
    guard.client_spoke(10.0, 18.0)
    assert guard.is_echo(10.2, 18.1)  # the speakers leaking into the mic


def test_my_own_turn_after_the_client_is_kept():
    guard = EchoGuard()
    guard.client_spoke(10.0, 18.0)
    assert not guard.is_echo(18.9, 22.0)


def test_echo_while_the_client_is_still_talking():
    guard = EchoGuard()
    assert guard.is_echo(5.1, 9.0, client_open_since=5.0)
    assert not guard.is_echo(5.1, 9.0, client_open_since=None)


def test_short_overlap_at_the_edge_is_kept():
    guard = EchoGuard()
    guard.client_spoke(0.0, 4.0)
    assert not guard.is_echo(3.5, 8.0)  # I start just before the client finishes


def test_old_spans_are_forgotten():
    guard = EchoGuard(keep_s=60)
    guard.client_spoke(0.0, 5.0)
    guard.client_spoke(100.0, 101.0)
    assert list(guard.client_spans) == [(100.0, 101.0)]
