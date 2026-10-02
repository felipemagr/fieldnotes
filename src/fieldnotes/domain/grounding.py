"""What the docs actually contain, so model output can be checked against it in code.

The prompt asks the model to name only documented endpoints and fields; this makes it certain.
An endpoint that is not in the docs is removed from the mapping (the panel shows "not in docs"),
a docs link that points nowhere is dropped, and field names the docs never mention are flagged.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from fieldnotes.domain.suggestion import Mapping

METHODS = "GET|POST|PUT|PATCH|DELETE"
# "POST /v2/declarations" inline, or "POST" on one line and the full URL on the next.
INLINE = re.compile(rf"\b({METHODS})\s+(/[^\s`?#]+)")
BLOCK = re.compile(rf"^({METHODS})\s*\n\s*(\S+)", re.MULTILINE)
REF = re.compile(r"\[ref: ([^\]]+)\]")
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def normalise_path(path: str) -> str:
    """`https://host/v2/{deal\\_id}/payments/bulk?dry_run=false` -> `/v2/{}/payments/bulk`."""
    path = path.replace("\\_", "_").strip("`'\".,)")
    if path.startswith("http"):
        path = urlparse(path).path
    path = path.split("?")[0].split("#")[0].rstrip("/")
    # Name path parameters the same way whatever the model calls them: {deal_id} == {dealId}.
    return re.sub(r"\{[^}]*\}", "{}", path) or "/"


def parse_endpoint(text: str) -> tuple[str, str] | None:
    m = re.match(rf"\s*({METHODS})\s+(\S+)", text or "", re.IGNORECASE)
    return (m.group(1).upper(), normalise_path(m.group(2))) if m else None


@dataclass
class DocsIndex:
    endpoints: set[tuple[str, str]] = field(default_factory=set)
    refs: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)

    @classmethod
    def from_markdown(cls, markdown: str) -> "DocsIndex":
        text = markdown.replace("\\_", "_")
        endpoints = {
            (method, normalise_path(path))
            for pattern in (INLINE, BLOCK)
            for method, path in pattern.findall(text)
            if path.startswith(("/", "http"))
        }
        return cls(endpoints, set(REF.findall(text)), set(SNAKE.findall(text)))

    def __bool__(self) -> bool:
        return bool(self.endpoints or self.refs)

    def check(self, mapping: Mapping) -> Mapping:
        """The mapping with anything the docs do not back up removed or flagged."""
        endpoint = mapping.endpoint
        if endpoint and parse_endpoint(endpoint) not in self.endpoints:
            endpoint = None
        doc_ref = mapping.doc_ref if mapping.doc_ref in self.refs else None
        unknown = sorted(
            {f for f in SNAKE.findall(f"{mapping.approach} {mapping.endpoint or ''}")} - self.fields
        )
        return mapping.model_copy(
            update={"endpoint": endpoint, "doc_ref": doc_ref, "unverified": unknown}
        )
