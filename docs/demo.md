# Two-minute demo

Run `./fieldnotes.sh --demo` and share the panel. You ask seven playbook questions; the client
answers. Point at the panel after each answer.

| You ask | Point at |
|---|---|
| How do you send loan data today? | **How it maps**: Excel → file adapter → `POST /v2/declarations`, with a docs link |
| What does the file look like? | **Risks**: day/month swap, decimal commas |
| Full portfolio or only changes? | **Ask next** never asks it: it heard the answer |
| What happens when a file has errors? | `dry_run` before sending; `external_id` stops double counting |
| How do repayments come in? | Stripe → our webhook intake → `payments/bulk`; risk: Madrid vs UTC cut-off |
| Anything unusual in the data? | **Ask next**: blank DPD, restructure ID. **Route to Ops**: do they still count? |
| Anything else you need from us? | Outbound webhook: **not in docs**. Advance rate: **Route to Ops** |

Then **End call**: the report has the plan with endpoints, questions for the client, items for
Ops, risks and a draft email that never mentions Ops or advance-rate terms.
