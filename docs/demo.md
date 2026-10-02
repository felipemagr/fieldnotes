# Two-minute demo

A script for showing Fieldnotes on a screen share, using the mock call in `demo/`.

1. **(15 s)** "On client calls, I spend half my head on notes. Fieldnotes listens, locally, and
   keeps the integration map for me. Audio is never stored."
2. **(15 s)** Run `fieldnotes run --replay demo/mock_call.txt --speed 1.5` (or a
   friend on a live call). Transcript fills the left column.
3. **(45 s)** As the client describes the Excel tape, point at **How it maps**: `POST
   /v2/declarations` with a link to the docs section, and dry_run before the real run. Stripe
   becomes a webhook intake on our side that posts to `payments/bulk`. "Only endpoints from the
   docs, and each one links to its section."
4. **(20 s)** **Ask next**: blank DPD, restructured loans, time zones. "It finds what the client
   has not said yet. Questions they answer drop off by themselves."
5. **(10 s)** **Route to Ops**: the advance-rate question. "Commercial and credit-agreement
   topics are not mine to answer, so it routes them."
6. **(15 s)** Click **End call**. The report appears: plan, endpoints, risks, open questions for
   Ops, a draft email. "Copy, edit, send myself. Nothing goes out automatically."
