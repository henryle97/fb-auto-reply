"""Summarize captured webhook payloads: one anonymized example per distinct shape.

    fb-auto-reply payloads logs/webhooks.jsonl

Input lines are either a raw payload or {"received_at": ..., "payload": {...}} (the
WEBHOOK_LOG_PATH / GET /debug/payloads format). Ids, names, messages and URLs are replaced
with stable placeholders so the output can be published.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_ID_KEYS = {
    "id",
    "post_id",
    "comment_id",
    "parent_id",
    "sender_id",
    "recipient_id",
    "photo_id",
    "video_id",
    "share_id",
}
_TEXT_KEYS = {"message", "name", "permalink_url", "link", "photo", "description"}


class Anonymizer:
    def __init__(self) -> None:
        self.ids: dict[str, str] = {}

    def _id(self, value: str) -> str:
        # Keep the "<owner>_<object>" structure of composite ids.
        return "_".join(
            self.ids.setdefault(p, str(9 * 10**14 + len(self.ids) + 1)) for p in value.split("_")
        )

    def __call__(self, obj: Any, key: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: self(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self(v, key) for v in obj]
        if isinstance(obj, str) and key in _ID_KEYS and re.fullmatch(r"[\d_]+", obj):
            return self._id(obj)
        if isinstance(obj, str) and key in _TEXT_KEYS:
            return f"<{key}>"
        return obj


def shape(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: shape(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [shape(obj[0])] if obj else []
    return type(obj).__name__


def load(path: str | Path) -> list[dict[str, Any]]:
    payloads = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            payloads.append(data.get("payload", data))
    return payloads


def distinct(payloads: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(label, anonymized single-change payload) for each distinct change shape."""
    seen: dict[str, tuple[str, dict[str, Any]]] = {}
    anonymize = Anonymizer()
    for payload in payloads:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                v = change.get("value", {})
                by_page = (v.get("from") or {}).get("id") == entry.get("id")
                label = f"{change.get('field')}: item={v.get('item')} verb={v.get('verb')}" + (
                    " (by the Page)" if by_page else ""
                )
                single = {**payload, "entry": [{**entry, "changes": [change]}]}
                key = label + json.dumps(shape(single), sort_keys=True)
                if key not in seen:
                    seen[key] = (label, anonymize(single))
    return sorted(seen.values(), key=lambda x: x[0])


def render(items: list[tuple[str, dict[str, Any]]]) -> str:
    out = []
    for label, payload in items:
        out.append(
            f"### {label}\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
        )
    return "\n".join(out)
