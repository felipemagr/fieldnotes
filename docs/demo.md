# Two-minute demo

Setup: `uv run fieldnotes run --name demo` in one terminal, `scripts/mock_call.sh` ready in a
second, headphones on, the panel shared on screen.

1. **(15 s)** "On client calls I spend half my head on notes. Fieldnotes listens on my Mac and
   keeps the integration map for me. Audio never leaves the laptop."
2. **(15 s)** Start `scripts/mock_call.sh`. Read your first line. The client answers, and the
   transcript fills on the left, ME and CLIENT apart.
3. **(45 s)** The client describes the Excel tape. Point at **How it maps**: Excel tape →
   `POST /v2/declarations`, with a link to the docs section, and `dry_run` before the real run.
   Stripe becomes our webhook intake posting to `payments/bulk`. "Only endpoints from the docs."
4. **(20 s)** **Ask next**: blank DPD, restructured loans, time zones. "It asks what the client
   has not said. Answered questions drop off."
5. **(10 s)** **Route to Ops**: the advance-rate question. "Commercial and credit-agreement
   topics are not mine to answer."
6. **(15 s)** Click **End call**. The report appears: plan, endpoints, risks, open questions for
   Ops and a draft email. "I edit and send it myself. Nothing goes out automatically."
