"""The running state of the call: every suggestion merged, deduplicated, newest first."""

import re
from difflib import SequenceMatcher
from itertools import count
from typing import Literal

from pydantic import BaseModel

from fieldnotes.domain.suggestion import Mapping, Suggestion

Section = Literal["needs", "mapping", "ask", "ops", "risks"]
SECTIONS: tuple[Section, ...] = ("needs", "mapping", "ask", "ops", "risks")
SIMILAR = 0.82


class Item(BaseModel):
    id: int
    section: Section
    text: str
    approach: str | None = None  # mapping only
    endpoint: str | None = None  # mapping only
    doc_ref: str | None = None  # mapping only
    round: int
    pinned: bool = False
    dismissed: bool = False
    answered: bool = False  # ask only: the client answered it


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", text.lower())).strip()


_STOPWORDS = (
    "a an the and or of to in on for per by at as is are be do does did can could would should "
    "will you your we our they their it its this that there any each with from into what which "
    "who how when where why if not no"
)
STOPWORDS = set(_STOPWORDS.split())


def content_words(text: str) -> set[str]:
    """Meaningful words, crudely singular: "payments" and "payment" count once."""
    return {w.removesuffix("s") for w in text.split() if w not in STOPWORDS and len(w) > 1}


def similar(a: str, b: str) -> bool:
    a, b = normalise(a), normalise(b)
    if not a or not b:
        return a == b
    if a == b or SequenceMatcher(None, a, b).ratio() >= SIMILAR:
        return True
    # Same point, other words: most content words of the shorter item appear in the longer one.
    # Items of one or two content words never match this way ("Time zones" must not swallow
    # "Month end in Madrid time or UTC").
    words_a, words_b = content_words(a), content_words(b)
    shorter = min(len(words_a), len(words_b))
    return shorter >= 3 and len(words_a & words_b) / shorter >= 0.6


class Board:
    def __init__(self) -> None:
        self.items: list[Item] = []
        self.round = 0
        self._ids = count(1)

    def _match(self, section: Section, text: str) -> Item | None:
        return next((i for i in self.items if i.section == section and similar(i.text, text)), None)

    def _add(self, section: Section, text: str, mapping: Mapping | None = None) -> Item | None:
        text = text.strip()
        if not text:
            return None
        existing = self._match(section, text)
        if existing:
            # A mapping can sharpen later: the docs endpoint arrives once the need is clear.
            if mapping and mapping.endpoint and not existing.endpoint and not existing.dismissed:
                existing.approach = mapping.approach
                existing.endpoint = mapping.endpoint
                existing.doc_ref = mapping.doc_ref
                existing.round = self.round
                return existing
            return None
        item = Item(id=next(self._ids), section=section, text=text, round=self.round)
        if mapping:
            item.approach = mapping.approach
            item.endpoint = mapping.endpoint
            item.doc_ref = mapping.doc_ref
        self.items.append(item)
        return item

    def merge(self, suggestion: Suggestion) -> list[Item]:
        """Fold one suggestion in. Returns the items that are new or changed."""
        self.round += 1
        changed: list[Item | None] = []
        changed += [self._add("needs", t) for t in suggestion.client_needs]
        changed += [self._add("mapping", m.need, m) for m in suggestion.fence_mapping]
        changed += [self._add("ask", t) for t in suggestion.questions_to_ask]
        changed += [self._add("ops", t) for t in suggestion.route_to_ops]
        changed += [self._add("risks", t) for t in suggestion.risks]
        for text in suggestion.answered_questions:
            if (item := self._match("ask", text)) and not item.pinned:
                item.answered = True
        return [i for i in changed if i and not i.answered]

    def get(self, item_id: int) -> Item:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def pin(self, item_id: int, pinned: bool = True) -> Item:
        item = self.get(item_id)
        item.pinned = pinned
        return item

    def dismiss(self, item_id: int) -> Item:
        item = self.get(item_id)
        item.dismissed, item.pinned = True, False
        return item

    def visible(self, section: Section) -> list[Item]:
        """Pinned first, then newest first. Dismissed items never come back."""
        shown = [i for i in self.items if i.section == section and not (i.dismissed or i.answered)]
        return sorted(shown, key=lambda i: (not i.pinned, -i.round, -i.id))

    def snapshot(self) -> dict:
        return {
            "round": self.round,
            "sections": {
                s: [{**i.model_dump(), "new": i.round == self.round} for i in self.visible(s)]
                for s in SECTIONS
            },
        }

    def open_questions(self) -> list[str]:
        return [i.text for i in self.visible("ask")]

    def brief(self) -> str:
        """What the board already says, in the Suggestion's own field names, for the model."""
        fields = {
            "needs": "client_needs",
            "mapping": "fence_mapping",
            "ask": "questions_to_ask (open)",
            "ops": "route_to_ops",
            "risks": "risks",
        }
        lines = []
        for section, field in fields.items():
            items = [i.text for i in self.items if i.section == section and not i.answered]
            if items:
                lines.append(f"{field}: " + " | ".join(items))
        return "\n".join(lines) or "(empty)"

    def as_text(self) -> str:
        """The board in plain words, for the post-call report prompt."""
        names = {
            "needs": "Client needs",
            "mapping": "How it maps",
            "ask": "Ask next",
            "ops": "Route to Ops",
            "risks": "Risks",
        }
        lines: list[str] = []
        for s in SECTIONS:
            lines.append(f"{names[s]}:")
            for i in self.visible(s):
                mark = " [PINNED by the engineer]" if i.pinned else ""
                extra = f" -> {i.approach} ({i.endpoint or 'no endpoint'})" if i.approach else ""
                lines.append(f"- {i.text}{extra}{mark}")
        answered = [i.text for i in self.items if i.answered]
        if answered:
            lines.append("Questions the client answered during the call: " + "; ".join(answered))
        dismissed = [i.text for i in self.items if i.dismissed]
        if dismissed:
            lines.append("Dismissed by the engineer (ignore): " + "; ".join(dismissed))
        return "\n".join(lines)
