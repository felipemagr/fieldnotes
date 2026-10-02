# Who owns what

Route every item by its owner. If the owner is unclear, it is a question for the client.

## Engineer (ME, the forward deployed engineer)

Owns how the client's data reaches the platform. Goes in `fence_mapping` (how) and `risks` (what
can break).

- Adapters on our side: parse files (Excel, CSV, PDF), receive webhooks, poll SFTP or APIs.
- Formats: dates, decimals, encodings, time zones, column mapping to documented fields.
- Delivery: channel, schedule, full snapshot vs delta, retries, restatements.
- Identifiers and idempotency (`external_id`), validation (`dry_run`), monitoring runs.
- Audit trail of what was sent and when, alerts when a file fails, duplicate prevention.

Examples: "Nightly CSV on SFTP, changes only" → SFTP adapter + a documented endpoint.
"We must show regulators what we submitted" → keep each submission and its run id: engineer,
not Ops.

## Ops (credit and commercial, internal)

Owns anything that depends on the credit agreement or on money. Goes only in `route_to_ops`, never
in `fence_mapping`, and never in the email to the client.

- Pricing, fees, advance rates, facility size, terms.
- Eligibility criteria, concentration limits, covenants, borrowing base, waterfall.
- What a clause means: day count, default definitions, how modified or charged-off assets count.

Examples: "What concentration limit applies to one merchant?" → Ops. "Do charged-off receivables
leave the borrowing base?" → Ops. "Which column holds the charge-off date?" → not Ops: ask the
client.

## Client

Owns their data and what it means. What we still need from them goes in `questions_to_ask`.

- What each field means, what a blank means, which values a status can take.
- Their systems and vendors, what they can and cannot change.
- Who sends the files, who to call when one breaks, their time zone and cut-off.

Examples: "Empty maturity date: open-ended, or missing?" → ask the client. "Who do we call when the
nightly file is late?" → ask the client.
