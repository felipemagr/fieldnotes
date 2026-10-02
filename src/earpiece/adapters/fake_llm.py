"""Canned answers in the order the demo call needs them. For development, tests and a demo
that must stand without the network."""

import asyncio
import json

from earpiece.app.brain import REPORT_MARKER

REF = "https://docs.fence.finance/"

CANNED: list[dict] = [
    {
        "client_needs": ["Read the vendor's Excel loan tape as it is, format cannot change"],
        "fence_mapping": [
            {
                "need": "Excel loan tape that cannot change",
                "approach": "File adapter on our side parses the sheet, maps columns to the "
                "facility fields and declares the book",
                "endpoint": "POST /v2/declarations",
                "doc_ref": REF + "#declaration-flow",
            }
        ],
        "questions_to_ask": [
            "Can you share a sample export and the column dictionary?",
            "Which column is the stable loan identifier?",
        ],
        "route_to_ops": [],
        "risks": ["Unknown fields are ignored silently: a misnamed column is dropped"],
    },
    {
        "client_needs": ["Dates dd/mm/yyyy and amounts with decimal commas (Spanish locale)"],
        "fence_mapping": [
            {
                "need": "Spanish date and number formats",
                "approach": "Normalise to ISO dates and dot decimals in the adapter before "
                "declaring; validate first with dry_run",
                "endpoint": "POST /v2/declarations",
                "doc_ref": REF + "#dry-run",
            }
        ],
        "questions_to_ask": ["Do amounts ever use a dot as thousands separator?"],
        "route_to_ops": [],
        "risks": ["Day and month swapped silently if a date is parsed with the wrong locale"],
    },
    {
        "client_needs": ["Monthly full-book snapshot, today sent by email on business day 3"],
        "fence_mapping": [
            {
                "need": "Monthly full snapshot",
                "approach": "One declaration per month; external_id upserts so a resend does "
                "not duplicate loans",
                "endpoint": "POST /v2/declarations",
                "doc_ref": REF + "#idempotency",
            }
        ],
        "questions_to_ask": [
            "Can the file land on SFTP instead of email?",
            "How should a repaid loan that disappears from the file be treated?",
        ],
        "route_to_ops": [],
        "risks": ["Email delivery has no audit trail and no retry"],
    },
    {
        "client_needs": ["Repayments arrive through Stripe webhooks"],
        "fence_mapping": [
            {
                "need": "Stripe repayments",
                "approach": "Webhook intake on our side stores events, dedupes by Stripe event "
                "id and posts intake transactions in batches",
                "endpoint": "POST /v2/{deal_id}/payments/bulk",
                "doc_ref": REF + "#payments-bulk",
            },
            {
                "need": "Stable contract number per loan",
                "approach": "Use the contract number as asset_external_id",
                "endpoint": "POST /v2/declarations",
                "doc_ref": REF + "#idempotency",
            },
        ],
        "questions_to_ask": ["How do you link a Stripe payment to a contract number?"],
        "route_to_ops": [],
        "risks": [
            "Webhooks arrive at least once and out of order: dedupe by event id",
            "payments/bulk defaults to dry_run=true: set it to false explicitly",
        ],
    },
    {
        "client_needs": [
            "Some loans have no days past due filled in",
            "Restructured loans keep the same contract number with a new schedule",
        ],
        "fence_mapping": [],
        "questions_to_ask": [
            "What does a blank DPD mean: no payment due yet, or unknown?",
            "Is there any field that flags a restructured loan, and its date?",
        ],
        "route_to_ops": ["Whether restructured loans stay eligible under the facility"],
        "risks": ["Blank DPD read as zero would overstate portfolio quality"],
    },
    {
        "client_needs": ["Signed contracts as PDFs, named by contract number (mostly)"],
        "fence_mapping": [
            {
                "need": "Loan contract PDFs",
                "approach": "Register documents, PUT bytes to the presigned URL, join to assets "
                "by document_external_id",
                "endpoint": "POST /v2/{deal_id}/documents",
                "doc_ref": REF + "#doc-register",
            }
        ],
        "questions_to_ask": ["How do we map the older PDFs named by customer?"],
        "route_to_ops": ["Higher advance rate for clean, on-time data"],
        "risks": ["Presigned URLs expire after 1 hour"],
    },
    {
        "client_needs": [
            "Check a file before submitting it",
            "Stop duplicate loans when a file is resent",
        ],
        "fence_mapping": [
            {
                "need": "Validate before sending",
                "approach": "Submit with dry_run true, read per-asset results, then resubmit",
                "endpoint": "POST /v2/declarations",
                "doc_ref": REF + "#dry-run",
            }
        ],
        "questions_to_ask": [
            "Who on your side gets the alert when a file fails validation?",
            "Is the month-end cut-off midnight Madrid time?",
        ],
        "route_to_ops": [],
        "risks": ["Month-end in Madrid time vs Stripe in UTC shifts payments across months"],
    },
]

REPORT = """## Summary
Spanish consumer lender, about 40,000 active loans. Monthly Excel loan tape from a vendor system
that cannot change, repayments through Stripe, contracts as PDFs.

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
