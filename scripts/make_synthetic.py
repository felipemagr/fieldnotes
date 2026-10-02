"""Write synthetic test data to data/synthetic/ (gitignored). Deterministic: same seed, same files.

    uv run python scripts/make_synthetic.py

calls/      transcripts to replay (`earpiece run --replay data/synthetic/calls/<file>`), each a
            situation the panel must handle; EXPECTED.md says what a good panel shows for each.
artifacts/  the files those clients talk about: a Spanish-locale loan tape with the traps the call
            mentions, Stripe webhook events with duplicates and out-of-order delivery, a contracts
            index with mixed file names. For building and testing adapters, not read by Earpiece.
"""

import csv
import json
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "synthetic"
rng = random.Random(7)

CALLS = {
    "sftp_nightly_delta.txt": """\
# A US earned-wage-access provider moving from API pilots to a facility. Delta files, PGP, restatements.
ME: Thanks for making the time. Can you walk me through how loan data leaves your systems today?
CLIENT: Sure. Every night at two a.m. Eastern we drop a CSV on our SFTP server, it is PGP encrypted, and it only contains the advances that changed that day.
ME: Only the changes, so a delta file.
CLIENT: Right, new advances, repayments, write-offs. If nothing changed for an advance it is not in the file.
CLIENT: The tricky bit is restatements. Sometimes payroll data arrives late and we resend a corrected file for a previous day, with the same file name.
ME: How would we know a file is a correction?
CLIENT: Honestly today you would not, unless someone emails you. Could your side detect that automatically?
CLIENT: Also our advance IDs changed format last year, old ones are numeric and new ones start with ADV dash.
CLIENT: And we will need to send employer documents, payroll confirmations, for every advance. Those are PDFs in an S3 bucket we own.
CLIENT: Who do we call when a file fails at three in the morning? Our on-call team is in Manila.
ME: Good question, let me note that.
""",
    "messy_asr.txt": """\
# Speech recognition noise: misheard terms, fillers, half sentences, crosstalk. The panel must stay sane.
ME: Okay so, um, can you hear me okay?
CLIENT: Yeah yeah. Sorry, the dog. Okay.
ME: No worries. So the loan tape.
CLIENT: Right so the loan tape, we export it from, uh, from Mambu, it's a CSV, and I think we could do the dry ron thing first? Like test it before it's real?
CLIENT: Mm.
ME: And the repayments?
CLIENT: Strype. All through Strype, the web hooks, they hit our back end and then we, we push them into the ledger at night.
CLIENT: Sorry, someone was, um. What was I saying. The external I.D., is that the contract number or our internal one, because we have both.
ME: We can pick one.
CLIENT: Okay. Yeah. Thank you.
""",
    "commercial_pushback.txt": """\
# A client who mostly wants to negotiate. Almost everything belongs to Ops, not to the engineer.
ME: Shall we start with how the data gets to us?
CLIENT: Before that, I want to understand the advance rate. Our last facility gave us eighty five percent and we expect at least that.
CLIENT: And the eligibility criteria, does a loan that was thirty days past due once stay ineligible forever, or only while it is late?
ME: I will make sure the right person answers that.
CLIENT: Also how does the waterfall work if collections drop below the threshold for two months in a row?
CLIENT: And the fees, is there a fee per declaration, because we would want to send data daily.
CLIENT: Fine. On the data side it is simple, we have a REST API with a list loans endpoint, paginated, you can just pull from it.
ME: Do you have rate limits on that API?
CLIENT: A hundred requests per minute, and the token expires every hour.
""",
    "quiet_client.txt": """\
# Short answers only. The trigger should rarely fire; questions should drive the call.
ME: How do you send the loan data today?
CLIENT: Excel.
ME: How often?
CLIENT: Monthly.
ME: By email?
CLIENT: Yes.
ME: Full portfolio or only changes?
CLIENT: Full.
ME: Do loans have a stable ID?
CLIENT: Yes, the contract number.
ME: Anything that worries you about the integration?
CLIENT: Not really, as long as we do not have to change the file.
""",
}

EXPECTED = """\
# What a good panel shows

## sftp_nightly_delta.txt
- Needs: nightly PGP CSV delta on SFTP; restatements resent with the same name; two ID formats; payroll PDFs.
- Maps: SFTP/PGP adapter (ours) -> POST /v2/declarations; documents -> POST /v2/{deal_id}/documents.
- Ask: how to tell a correction file from a new one; mapping old numeric IDs to ADV- IDs; who is on call.
- Risks: same file name on restatement; ID format change breaks idempotency; deltas need a full-book reconciliation.

## messy_asr.txt
- "dry ron" read as dry_run, "Strype" as Stripe, "external I.D." as external_id.
- Short turns ("Mm.", "Okay. Yeah.") never trigger an update on their own.
- Ask: contract number or internal ID as asset_external_id.

## commercial_pushback.txt
- Route to Ops: advance rate, eligibility after a past DPD, waterfall, per-declaration fees.
- Nothing about those in "How it maps".
- Maps: a pull adapter (ours) over their paginated REST API; risks: rate limit 100/min, hourly token expiry.

## quiet_client.txt
- Few updates; a client question or a long turn is needed to trigger.
- The board should not invent needs the client did not state.
"""


def spanish_amount(x: float) -> str:
    whole, cents = f"{x:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{cents}"


def loan_tape(path: Path) -> None:
    """One row per loan, as a Spanish LMS exports it: `;` separated, dd/mm/yyyy, decimal commas.

    Traps: blank DPD on new loans and on a few old ones; restructured loans shown only as ACTIVO;
    one loan duplicated with a different balance; amounts above 1.000 with a dot thousands
    separator; one date in the US order.
    """
    rows = []
    for n in range(1, 401):
        originated = date(2025, 1, 1) + timedelta(days=rng.randint(0, 600))
        principal = rng.choice([300, 600, 900, 1200, 2500, 4000, 6000])
        outstanding = round(principal * rng.uniform(0.1, 1.0), 2)
        dpd = rng.choice([0] * 12 + [5, 15, 31, 62, 95])
        status = "ACTIVO"
        if originated > date(2026, 8, 15):
            dpd = ""  # no instalment due yet
        elif n % 37 == 0:
            dpd = ""  # unexplained blank
        # Restructured loans stay ACTIVO; only a free-text note sometimes says so.
        note = "reestructurado" if n % 53 == 0 else ""
        rows.append(
            {
                "num_contrato": f"ES-{2025000 + n}",
                "fecha_alta": originated.strftime("%d/%m/%Y"),
                "importe_principal": spanish_amount(principal),
                "saldo_pendiente": spanish_amount(outstanding),
                "dias_impago": dpd,
                "estado": status,
                "producto": rng.choice(["TPV", "PERSONAL"]),
                "observaciones": note,
            }
        )
    dup = dict(rows[10])
    dup["saldo_pendiente"] = spanish_amount(123.45)
    rows.append(dup)
    rows[20]["fecha_alta"] = "09/13/2025"  # month and day swapped
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def stripe_events(path: Path) -> None:
    """Webhook payloads as delivered: some twice, some out of order, some failed."""
    events = []
    t0 = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)  # 23:00 Madrid: month end edge
    for n in range(60):
        ok = rng.random() > 0.15
        created = t0 + timedelta(minutes=7 * n)
        events.append(
            {
                "id": f"evt_{rng.getrandbits(48):012x}",
                "type": "payment_intent.succeeded" if ok else "payment_intent.payment_failed",
                "created": int(created.timestamp()),
                "data": {
                    "object": {
                        "id": f"pi_{rng.getrandbits(48):012x}",
                        "amount": rng.choice([4999, 8250, 12000, 15075]),
                        "currency": "eur",
                        "metadata": {"contract": f"ES-{2025000 + rng.randint(1, 400)}"}
                        if n % 11
                        else {},  # some payments carry no contract reference
                    }
                },
            }
        )
    delivered = events + [events[i] for i in (3, 17, 17, 42)]  # at least once
    rng.shuffle(delivered)  # out of order
    path.write_text("\n".join(json.dumps(e) for e in delivered) + "\n", encoding="utf-8")


def contracts_index(path: Path) -> None:
    rows = []
    for n in range(1, 401):
        name = f"ES-{2025000 + n}.pdf"
        if n < 60:
            name = f"contrato_{rng.choice(['garcia', 'lopez', 'martin', 'sanchez'])}_{n}.pdf"
        if n % 97 == 0:
            continue  # missing contract
        rows.append(
            {"file_name": name, "folder": "contratos/2025" if n < 200 else "contratos/2026"}
        )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file_name", "folder"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    (OUT / "calls").mkdir(parents=True, exist_ok=True)
    (OUT / "artifacts").mkdir(parents=True, exist_ok=True)
    for name, text in CALLS.items():
        (OUT / "calls" / name).write_text(text, encoding="utf-8")
    (OUT / "calls" / "EXPECTED.md").write_text(EXPECTED, encoding="utf-8")
    loan_tape(OUT / "artifacts" / "loan_tape_2026-09.csv")
    stripe_events(OUT / "artifacts" / "stripe_events.jsonl")
    contracts_index(OUT / "artifacts" / "contracts_index.csv")
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            print(path.relative_to(OUT.parent.parent))


if __name__ == "__main__":
    main()
