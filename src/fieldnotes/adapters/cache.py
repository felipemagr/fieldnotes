"""One JSON file per key."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class JsonCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def path(self, key: str) -> Path:
        return self.directory / f"{slug(key)}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["payload"]

    def put(self, key: str, payload: dict[str, Any]) -> Path:
        path = self.path(key)
        entry = {"key": key, "stored_at": datetime.now(UTC).isoformat(), "payload": payload}
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
