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

Examples: "Excel tape, format fixed" → file adapter + `POST /v2/declarations`.
"Prove what we sent" → keep each submission and its run id: engineer, not Ops.

## Ops (credit and commercial, internal)

Owns anything that depends on the credit agreement or on money. Goes only in `route_to_ops`, never
in `fence_mapping`, and never in the email to the client.

- Pricing, fees, advance rates, facility size, terms.
- Eligibility criteria, concentration limits, covenants, borrowing base, waterfall.
- What a clause means: day count, default definitions, how restructured loans count.

Examples: "Higher advance rate if data is clean?" → Ops. "Do restructured loans stay eligible?" →
Ops. "Is there a column that flags a restructure?" → not Ops: ask the client.

## Client

Owns their data and what it means. What we still need from them goes in `questions_to_ask`.

- What each field means, what a blank means, which values a status can take.
- Their systems and vendors, what they can and cannot change.
- Who sends the files, who to call when one breaks, their time zone and cut-off.

Examples: "Blank DPD: not due yet, or unknown?" → ask the client. "Who gets the alert when a file
fails?" → ask the client.
