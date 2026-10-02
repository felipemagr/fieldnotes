# Two-minute demo

Run `./fieldnotes.sh --demo`, share the panel. Each client line shows one capability.

| Client says | Point at |
|---|---|
| Monthly Excel export, vendor format, Spanish dates and decimals | **How it maps**: file adapter → `POST /v2/declarations`, with a docs link. **Risks**: day/month swap, decimal commas |
| The whole book every month | **Ask next** never asks "full book or changes?": it heard the answer |
| Errors found a week later, loans counted twice, can we check first? | `dry_run` before the real run; `external_id` stops duplicates |
| Stripe webhooks, Madrid month end vs UTC | Our webhook intake → `payments/bulk`; risks: out-of-order events, time-zone cut-off |
| Blank DPD, restructured loans keep their number, do they still count? | **Ask next**: blank DPD, restructure flag. **Route to Ops**: eligibility |
| Can your platform send us a webhook? | Not in the docs: flagged, no invented endpoint |
| Higher advance rate for clean data? | **Route to Ops** |

Then **End call**: the report (Opus) has the plan with endpoints, questions for the client, items
for Ops, risks and a draft email that never mentions Ops or the advance-rate terms.
