"""The Brain: one conversation per call with the model, docs loaded once, turns sent in batches."""

import asyncio
import logging
import time

from pydantic import ValidationError

from fieldnotes.domain.suggestion import Suggestion, parse_suggestion
from fieldnotes.domain.turn import Turn
from fieldnotes.ports import LLM

logger = logging.getLogger(__name__)

REPORT_MARKER = "THE CALL HAS ENDED."

SYSTEM_PROMPT = """\
You help a Forward Deployed Engineer during a live call with a client of an asset-backed finance
platform. The platform's API documentation is given in the first message. You then receive the
transcript turn by turn ("ME" is the engineer, "CLIENT" is the client). The transcript comes from
speech recognition, so expect small errors.

After each new batch of turns, return ONLY a JSON object, no prose, no code fence:
{"client_needs": [str], "fence_mapping": [{"need": str, "approach": str, "endpoint": str|null,
"doc_ref": str|null}], "questions_to_ask": [str], "route_to_ops": [str], "risks": [str],
"answered_questions": [str]}

Rules:
- Only name endpoints, fields and behaviours that appear in the documentation. endpoint is the
  method and path exactly as documented (e.g. "POST /v2/declarations"). doc_ref is the URL from
  the [ref: ...] tag of the section you used. If something is not in the docs, set endpoint and
  doc_ref to null and say "not in docs, ask" in approach.
- The platform does not read client systems. Anything that adapts the client's side (parsing a
  file, receiving a webhook, polling an SFTP folder) is an adapter the engineer builds, which then
  calls a documented endpoint. Say so in approach.
- Never decide what a credit agreement clause means (eligibility, covenants, waterfall, rates,
  day count). Put those under route_to_ops.
- Commercial topics (pricing, advance rates, fees, terms) go under route_to_ops.
  An item under route_to_ops never also appears in fence_mapping or client_needs.
- questions_to_ask finds what the client has NOT specified: data format, delivery channel and
  timing, full snapshot vs delta, identifiers, what a blank field means, status codes, time zones,
  restatements, who to contact when a file breaks. Phrase each as a question the engineer can
  say aloud. Never ask what the client already answered.
- Domain hints: loan tape = one row per asset per snapshot; DPD = days past due; declarations =
  how assets reach the platform; dry_run = validate without persisting; external_id = idempotency
  key; webhooks arrive at least once and out of order.
- client_needs are in the client's words ("Excel export we cannot change"), not engineering tasks.
- Each message lists the questions still open on the engineer's board. Never add one that means
  the same as an open one. If the new turns answer an open question, copy it verbatim into
  answered_questions.
- Be short: every item 15 words at most. Max 3 new items per section per update, fewer is better.
  Do not repeat items already given unless they changed. Empty lists are fine.
- English only."""

CONTEXT_TEMPLATE = """\
Platform API documentation follows. Read it now; the call starts after it.
Reply with exactly: OK

<documentation>
{docs}
</documentation>"""

REPORT_PROMPT = """\
{marker} Write the post-call report in markdown, for the engineer to edit. No JSON, no title:
start directly with "## Summary". Use exactly these sections:
## Summary
## Decisions made
## Open questions for Ops
## Integration plan
(numbered steps; name data sources and only documented endpoints)
## Risks
## Draft follow-up email
(mark it DRAFT; the engineer edits and sends it, nothing is sent automatically)

The whole call, start to end:
{turns}

The engineer's board at the end of the call:
{board}"""


def format_turns(turns: list[Turn]) -> str:
    return "\n".join(t.line() for t in turns) or "(none)"


class Brain:
    def __init__(
        self,
        llm: LLM,
        start_timeout_s: float = 60.0,
        timeout_s: float = 30.0,
        report_timeout_s: float = 120.0,
    ):
        self.llm = llm
        self.start_timeout_s = start_timeout_s
        self.timeout_s = timeout_s
        self.report_timeout_s = report_timeout_s
        self._docs = ""
        self._healthy = False

    @property
    def max_analyse_s(self) -> float:
        """The longest one `analyse` can take: a restart, a call and its retry."""
        return self.start_timeout_s + 2 * self.timeout_s

    async def _send(self, message: str, timeout_s: float | None = None) -> str:
        """One model call, cut off after the time limit (raises TimeoutError).

        After a failure the session is restarted first, on its own time budget. The new session
        has the docs but not the earlier turns; open questions travel with every message.
        """
        if not self._healthy:
            logger.warning("Restarting the model session after a failed call")
            await self.start(self._docs)
        try:
            async with asyncio.timeout(timeout_s or self.timeout_s):
                return await self.llm.send(message)
        except BaseException:
            self._healthy = False
            raise

    @property
    def model(self) -> str:
        return self.llm.model

    async def start(self, docs_markdown: str) -> None:
        t = time.perf_counter()
        self._docs = docs_markdown
        async with asyncio.timeout(self.start_timeout_s):
            await self.llm.start(SYSTEM_PROMPT, CONTEXT_TEMPLATE.format(docs=docs_markdown))
        self._healthy = True
        logger.info("Brain ready in %.1fs (%s)", time.perf_counter() - t, self.model)

    async def analyse(
        self, turns: list[Turn], open_questions: list[str] | None = None
    ) -> Suggestion | None:
        """A Suggestion for the new turns, or None when the model does not give a valid one."""
        t = time.perf_counter()
        still_open = "\n".join(f"- {q}" for q in open_questions or []) or "(none)"
        prompt = (
            f"New turns:\n{format_turns(turns)}\n\n"
            f"Questions still open on the board:\n{still_open}\n\nReturn the JSON object."
        )
        answer = await self._send(prompt)
        try:
            suggestion = parse_suggestion(answer)
        except (ValueError, ValidationError) as first:
            logger.warning("Answer was not a Suggestion (%s), retrying once", first)
            answer = await self._send("Return only the JSON object.")
            try:
                suggestion = parse_suggestion(answer)
            except (ValueError, ValidationError) as second:
                logger.error("Skipping this batch, still no valid JSON: %s", second)
                return None
        logger.info("Brain answered %d turns in %.2fs", len(turns), time.perf_counter() - t)
        return suggestion

    async def report(self, transcript: list[Turn], board_text: str) -> str:
        prompt = REPORT_PROMPT.format(
            marker=REPORT_MARKER, turns=format_turns(transcript), board=board_text
        )
        return (await self._send(prompt, self.report_timeout_s)).strip()

    async def close(self) -> None:
        await self.llm.close()
