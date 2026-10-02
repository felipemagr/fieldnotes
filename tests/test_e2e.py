"""The whole pipeline over HTTP: replay -> trigger -> FakeLLM -> board -> SSE -> report."""

import json
import socket
import threading
import time

import httpx
import uvicorn

from fieldnotes.adapters.fake_llm import FakeLLM
from fieldnotes.adapters.replay import ReplaySource
from fieldnotes.app.brain import Brain
from fieldnotes.app.pipeline import CallSession
from fieldnotes.app.server import create_app
from fieldnotes.domain.trigger import TurnTrigger

CALL = """\
ME: Thanks for joining.
CLIENT: Our loan tape is an Excel export from the loan system and we cannot change the format at all.
CLIENT: Can we get a higher advance rate?
ME: I will check.
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_replay_streams_turns_board_and_report(tmp_path):
    transcript = tmp_path / "call.txt"
    transcript.write_text(CALL)
    session = CallSession(
        source=ReplaySource(transcript, speed=20),
        brain=Brain(FakeLLM(delay_s=0.05)),
        docs_loader=lambda: "docs",
        calls_dir=tmp_path / "calls",
        name="e2e test",
        trigger=TurnTrigger(min_words=15, debounce_s=0),
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(session), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/api/state").json()["brain_ready"]:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(0.05)

        events = []
        with httpx.stream("GET", f"{base}/events", timeout=10) as stream:
            lines = stream.iter_lines()
            first = json.loads(next(lines).removeprefix("data: "))
            assert first["type"] == "snapshot" and first["started_at"]
            seen = len(first["transcript"])  # replay starts with the server
            sent_end = False
            for line in lines:
                if not line.startswith("data: "):
                    continue
                event = json.loads(line.removeprefix("data: "))
                events.append(event)
                turns = [e for e in events if e["type"] == "turn"]
                if seen + len(turns) == 4 and not sent_end:
                    time.sleep(0.3)  # let the last update land
                    httpx.post(f"{base}/api/end")
                    sent_end = True
                if event["type"] == "report":
                    break

        kinds = [e["type"] for e in events]
        assert seen + kinds.count("turn") == 4
        assert "board" in kinds
        board = next(e for e in events if e["type"] == "board")["board"]
        assert board["sections"]["needs"]
        report = next(e for e in events if e["type"] == "report")
        assert "Started:" in report["report"]
        saved = (tmp_path / "calls").glob("*-e2e-test.md")
        assert len(list(saved)) == 1
        record = json.loads(next((tmp_path / "calls").glob("*.call.json")).read_text())
        assert record["started_at"] and record["audio_stored"] is False

        # pin and dismiss go through the API
        item = board["sections"]["needs"][0]["id"]
        assert httpx.post(f"{base}/api/items/{item}/pin").status_code == 200
        assert httpx.post(f"{base}/api/items/{item}/dismiss").status_code == 200
        assert httpx.post(f"{base}/api/items/9999/dismiss").status_code == 404
        state = httpx.get(f"{base}/api/state").json()
        assert all(i["id"] != item for i in state["board"]["sections"]["needs"])
    finally:
        server.should_exit = True
        thread.join(timeout=5)
