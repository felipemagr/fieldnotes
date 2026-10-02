from fieldnotes.domain.grounding import DocsIndex, normalise_path
from fieldnotes.domain.suggestion import Mapping

DOCS = """\
### 3.2 Declaration Flow [ref: https://docs.example.com/#declaration-flow]

POST
https://api.example.com/v2/declarations

Send `asset_external_id` and `dry_run`.

### 5.1 Bulk Create [ref: https://docs.example.com/#payments-bulk]

POST
https://api.example.com/v2/{deal\\_id}/payments/bulk?dry\\_run=false

Poll `GET /v2/declarations/{run_id}` every 10 seconds.
"""

INDEX = DocsIndex.from_markdown(DOCS)


def mapping(endpoint, approach="adapter", doc_ref=None):
    return Mapping(need="n", approach=approach, endpoint=endpoint, doc_ref=doc_ref)


def test_index_reads_both_endpoint_styles():
    assert INDEX.endpoints == {
        ("POST", "/v2/declarations"),
        ("POST", "/v2/{}/payments/bulk"),
        ("GET", "/v2/declarations/{}"),
    }


def test_documented_endpoint_is_kept_even_with_query_and_other_param_names():
    m = INDEX.check(mapping("post /v2/{dealId}/payments/bulk?dry_run=true"))
    assert m.endpoint == "post /v2/{dealId}/payments/bulk?dry_run=true"


def test_invented_endpoint_is_removed():
    assert INDEX.check(mapping("POST /v2/webhooks")).endpoint is None
    assert INDEX.check(mapping("POST /v2/payments/bulk")).endpoint is None  # missing {deal_id}


def test_unknown_docs_link_is_dropped():
    assert INDEX.check(mapping(None, doc_ref="https://docs.example.com/#nope")).doc_ref is None
    ok = "https://docs.example.com/#payments-bulk"
    assert INDEX.check(mapping(None, doc_ref=ok)).doc_ref == ok


def test_unknown_field_names_are_flagged():
    m = INDEX.check(
        mapping(None, approach="Send asset_external_id and borrower_score, dry_run first")
    )
    assert m.unverified == ["borrower_score"]


def test_normalise_path():
    assert normalise_path("https://h/v2/{deal\\_id}/payments/bulk/?x=1") == "/v2/{}/payments/bulk"
