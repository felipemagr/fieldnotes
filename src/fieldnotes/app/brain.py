"""The Brain: one conversation per call with the model, docs loaded once, turns sent in batches."""

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from pydantic import ValidationError

from fieldnotes.domain.grounding import DocsIndex
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
- Route every item by "Who owns what" at the end of this prompt. Never decide what a credit
  agreement clause means. An item under route_to_ops never appears in another section.
- questions_to_ask finds what the client has NOT specified: data format, delivery channel and
  timing, full snapshot vs delta, identifiers, what a blank field means, status codes, time zones,
  restatements, who to contact when a file breaks. Phrase each as a question the engineer can
  say aloud. Never ask what the client already answered.
- Domain hints: loan tape = one row per asset per snapshot; DPD = days past due; declarations =
  how assets reach the platform; dry_run = validate without persisting; external_id = idempotency
  key; webhooks arrive at least once and out of order.
- client_needs are in the client's words ("CSV we cannot change"), not engineering tasks.
- Each message shows what is already on the engineer's board. Never repeat, rephrase or split an
  item that is there; add only what the new turns reveal. If the new turns answer an open
  question, copy it verbatim into answered_questions. Never ask what the transcript already
  answered.
- The engineer reads the board mid-call in one glance. Write like notes, not sentences:
  - client_needs, route_to_ops, risks: 8 words at most. Drop articles and filler.
  - questions_to_ask: 12 words at most, one question, said the way a person asks it.
  - fence_mapping: need 4 words at most; approach 10 words at most and never repeats the
    endpoint (the panel shows it next to the need).
  - No adverbs, no hedging ("might", "consider", "ensure", "clarify", "confirm"), no em dashes.
  - Name the specific thing: "Empty charge-off date read as open" beats "Data quality issues".
  Good: "Nightly CSV, changes only" / "Empty maturity date: open-ended, or missing?" /
  "Timestamps have no offset". Bad: "The client needs an integration that can parse...".
- Add an item only if the engineer would act on it during this call. At most 1 new item per
  section per update; empty lists are the normal case. Repeat nothing already given.
- English only."""

TEAMS_FILE = Path(__file__).resolve().parent.parent / "teams.md"


def system_prompt(teams: str) -> str:
    """The rules plus the ownership guide (teams.md), which says where each item goes."""
    return f"{SYSTEM_PROMPT}\n\n{teams.strip()}"


CONTEXT_TEMPLATE = """\
Platform API documentation follows. Read it now; the call starts after it.
Reply with exactly: OK

<documentation>
{docs}
</documentation>"""

REPORT_PROMPT = """\
{marker} Write the post-call report in markdown, for the engineer to edit. No JSON, no title:
start directly with "## Summary". Every section is a list of bullets of 15 words at most, except
the email. No adverbs, no hedging, no em dashes, no restating the transcript.
Use exactly these sections:
## Summary
(exactly 3 bullets)
## Decisions made
## Ask the client
(what the client still has to tell us: data, formats, fields, delivery, contacts. Never
commercial topics: those go only under For Ops)
## For Ops (internal)
(commercial and credit-agreement topics only: pricing, advance rates, eligibility, covenants)
## Integration plan
(numbered steps. The engineer's adapters read the client's files and events and call the
platform; the client does not call our adapters. Name data sources and only documented endpoints)
## Risks
## Draft follow-up email
(to the client. Mark it DRAFT, under 120 words. Ask only the "Ask the client" questions. Never
mention Ops, any internal team or our credit terms; for commercial questions the client raised,
write "we will come back to you on <topic>". Nothing is sent automatically)

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
        teams: str | None = None,
        report_llm: LLM | None = None,
    ):
        self.llm = llm
        self.report_llm = report_llm  # a stronger model for the report; the live one if None
        self.report_model: str | None = None  # which model wrote the last report
        self.system_prompt = system_prompt(teams or TEAMS_FILE.read_text(encoding="utf-8"))
        self.start_timeout_s = start_timeout_s
        self.timeout_s = timeout_s
        self.report_timeout_s = report_timeout_s
        self._docs = ""
        self.docs_index = DocsIndex()
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
        self.docs_index = DocsIndex.from_markdown(docs_markdown)
        async with asyncio.timeout(self.start_timeout_s):
            await self.llm.start(self.system_prompt, CONTEXT_TEMPLATE.format(docs=docs_markdown))
        self._healthy = True
        logger.info("Brain ready in %.1fs (%s)", time.perf_counter() - t, self.model)

    async def analyse(self, turns: list[Turn], board: str = "(empty)") -> Suggestion | None:
        """A Suggestion for the new turns, or None when the model does not give a valid one."""
        t = time.perf_counter()
        prompt = (
            f"New turns:\n{format_turns(turns)}\n\n"
            f"Already on the board (dismissed items included):\n{board}\n\n"
            "Return the JSON object with only what these turns add."
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
        return self.ground(suggestion)

    def ground(self, suggestion: Suggestion) -> Suggestion:
        """Keep only endpoints and docs links the docs contain; flag unknown field names."""
        if not self.docs_index:
            return suggestion
        checked = []
        for mapping in suggestion.fence_mapping:
            fixed = self.docs_index.check(mapping)
            if fixed.endpoint != mapping.endpoint or fixed.unverified:
                logger.warning(
                    "Not in the docs: endpoint %r, fields %s", mapping.endpoint, fixed.unverified
                )
            checked.append(fixed)
        return suggestion.model_copy(update={"fence_mapping": checked})

    async def report(self, transcript: list[Turn], board_text: str) -> str:
        prompt = REPORT_PROMPT.format(
            marker=REPORT_MARKER, turns=format_turns(transcript), board=board_text
        )
        if self.report_llm is not None:
            try:
                async with asyncio.timeout(self.start_timeout_s):
                    await self.report_llm.start(
                        self.system_prompt, CONTEXT_TEMPLATE.format(docs=self._docs)
                    )
                async with asyncio.timeout(self.report_timeout_s):
                    text = await self.report_llm.send(prompt)
                self.report_model = self.report_llm.model
                return text.strip()
            except Exception as e:  # TimeoutError included: fall back to the live model
                logger.warning(
                    "Report with %s failed (%r); using %s", self.report_llm.model, e, self.model
                )
            finally:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.report_llm.close(), 5)
        self.report_model = self.model
        return (await self._send(prompt, self.report_timeout_s)).strip()

    async def close(self) -> None:
        await self.llm.close()
