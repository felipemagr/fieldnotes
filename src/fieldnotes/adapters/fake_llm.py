"""Canned answers in the order the demo call needs them. For development, tests and a demo
that must stand without the network."""

import asyncio
import json

from fieldnotes.app.brain import REPORT_MARKER

REF = "https://docs.fence.finance/"


def mapping(need: str, approach: str, endpoint: str | None, anchor: str | None) -> dict:
    ref = REF + "#" + anchor if anchor else None
    return {"need": need, "approach": approach, "endpoint": endpoint, "doc_ref": ref}


DECLARE = "POST /v2/declarations"

CANNED: list[dict] = [
    {
        "client_needs": ["Excel tape, format fixed by vendor"],
        "fence_mapping": [
            mapping(
                "Excel loan tape",
                "Our file adapter maps columns, declares the book",
                DECLARE,
                "declaration-flow",
            )
        ],
        "questions_to_ask": ["Can you send a sample file?", "Which column is the loan ID?"],
        "risks": ["Misnamed column dropped without error"],
    },
    {
        "client_needs": ["Dates dd/mm/yyyy, decimal commas"],
        "fence_mapping": [
            mapping(
                "Spanish formats", "Normalise in adapter, validate with dry_run", DECLARE, "dry-run"
            )
        ],
        "questions_to_ask": ["Any dots as thousands separators?"],
        "risks": ["Day and month swapped on parse"],
    },
    {
        "client_needs": ["Full book monthly, by email, day 3"],
        "fence_mapping": [
            mapping(
                "Monthly snapshot",
                "One declaration a month; external_id stops duplicates",
                DECLARE,
                "idempotency",
            )
        ],
        "questions_to_ask": ["Could the file land on SFTP?", "Repaid loans just vanish?"],
        "risks": ["Email: no audit trail, no retry"],
    },
    {
        "client_needs": ["Repayments via Stripe webhooks"],
        "fence_mapping": [
            mapping(
                "Stripe repayments",
                "Our webhook intake dedupes, posts in batches",
                "POST /v2/{deal_id}/payments/bulk",
                "payments-bulk",
            ),
            mapping("Contract number", "Use as asset_external_id", DECLARE, "idempotency"),
        ],
        "questions_to_ask": ["How does a Stripe payment name its contract?"],
        "risks": ["Webhooks repeat and arrive out of order", "payments/bulk defaults to dry_run"],
    },
    {
        "client_needs": ["Some loans have blank DPD", "Restructured loans keep their number"],
        "questions_to_ask": [
            "Blank DPD: not due yet, or unknown?",
            "Does any column flag a restructure?",
        ],
        "route_to_ops": ["Restructured loans: still eligible?"],
        "risks": ["Blank DPD read as 0"],
    },
    {
        "client_needs": ["Contract PDFs, mostly named by contract"],
        "fence_mapping": [
            mapping(
                "Contract PDFs",
                "Register, upload to presigned URL, join by ID",
                "POST /v2/{deal_id}/documents",
                "doc-register",
            )
        ],
        "questions_to_ask": ["Older PDFs named by customer: any lookup?"],
        "route_to_ops": ["Higher advance rate for clean data?"],
        "risks": ["Presigned URLs expire in 1 hour"],
    },
    {
        "client_needs": ["Check files before sending", "No double-counted loans on resend"],
        "fence_mapping": [
            mapping(
                "Check before sending",
                "dry_run, read per-asset results, resubmit",
                DECLARE,
                "dry-run",
            )
        ],
        "questions_to_ask": [
            "Who gets the alert when a file fails?",
            "Month end: midnight Madrid time?",
        ],
        "risks": ["Madrid vs UTC shifts payments across months"],
    },
]

REPORT = """## Summary
- Spanish consumer lender, about 40,000 active loans.
- Monthly Excel tape, format fixed; repayments via Stripe.
- Contracts as PDFs, mostly named by contract number.

## Decisions made
- Build a file adapter for the Excel tape; normalise dates and decimal commas.
- Use the contract number as the asset identifier.

## Open questions for Ops
- Higher advance rate if data is clean and on time.
- Eligibility of restructured loans.

## Integration plan
1. Sample file and column dictionary from the client.
2. File adapter: parse, normalise, map to facility fields.
3. `POST /v2/declarations` with `dry_run: true`, review per-asset results, then `dry_run: false`.
4. Stripe webhook intake, deduped, posting to `POST /v2/{deal_id}/payments/bulk`.
5. Contracts: `POST /v2/{deal_id}/documents`, PUT to presigned URLs.

## Risks
- Blank DPD on a few hundred loans; restructured loans not flagged.
- Madrid vs UTC at month end.

## Draft follow-up email (DRAFT, edit before sending)
Hi, thanks for the time today. Below is a summary and the next steps we discussed...
"""


class FakeLLM:
    model = "fake"

    def __init__(self, delay_s: float = 0.4):
        self.delay_s = delay_s
        self.calls = 0
        self.messages: list[str] = []

    async def start(self, system_prompt: str, context: str) -> None:
        pass

    async def send(self, message: str) -> str:
        self.messages.append(message)
        await asyncio.sleep(self.delay_s)
        if REPORT_MARKER in message:
            return REPORT
        answer = CANNED[self.calls % len(CANNED)]
        self.calls += 1
        return "Here you go:\n```json\n" + json.dumps(answer) + "\n```"

    async def close(self) -> None:
        pass
