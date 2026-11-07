"""Handle one comment: filter -> claim -> choose a reply -> public reply -> private reply."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings
from .facebook import FacebookError
from .rules import Reply, RuleSet
from .store import Store

log = logging.getLogger(__name__)

Generate = Callable[[str, str, str], Awaitable[Reply | None]]
_MAX_OWN_IDS = 10_000


class Graph(Protocol):
    async def reply_comment(self, comment_id: str, message: str) -> dict[str, Any]: ...
    async def private_reply(self, page_id: str, comment_id: str, message: str) -> Any: ...
    async def get_post_text(self, post_id: str) -> str: ...


@dataclass
class CommentEvent:
    comment_id: str
    post_id: str
    from_id: str
    from_name: str
    message: str


def extract_comment_events(payload: dict[str, Any], page_id: str) -> list[CommentEvent]:
    """New comments from people other than the Page itself, from a `feed` webhook payload."""
    if payload.get("object") != "page":
        return []
    events = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            v = change.get("value", {})
            if v.get("item") != "comment" or v.get("verb") != "add":
                continue
            sender = v.get("from", {})
            if sender.get("id") == page_id:
                continue  # the Page's own comments, including the bot's replies
            if not v.get("comment_id") or not v.get("message", "").strip():
                continue  # photo or sticker only
            events.append(
                CommentEvent(
                    comment_id=v["comment_id"],
                    post_id=v.get("post_id", ""),
                    from_id=sender.get("id", ""),
                    from_name=sender.get("name", ""),
                    message=v["message"],
                )
            )
    return events


class Processor:
    def __init__(
        self,
        settings: Settings,
        rules: RuleSet,
        graph: Graph,
        store: Store,
        generate: Generate | None,
    ):
        self.s = settings
        self.rules = rules
        self.graph = graph
        self.store = store
        self.generate = generate
        # IDs of comments the bot posted: guards against replying to itself
        # if a webhook ever arrives without `from.id`.
        self.own_comment_ids: set[str] = set()

    async def choose_reply(self, ev: CommentEvent) -> Reply | None:
        reply = self.rules.match(ev.message, ev.from_name)
        if reply:
            return reply
        if self.s.ai_enabled and self.generate:
            post_text = await self.graph.get_post_text(ev.post_id) if ev.post_id else ""
            # None means the model declined (spam etc.): do not fall back to the default.
            # AIError propagates and is recorded as status=error.
            return await self.generate(ev.message, ev.from_name, post_text)
        return self.rules.default_reply(ev.message, ev.from_name)

    async def handle(self, ev: CommentEvent) -> None:
        if ev.comment_id in self.own_comment_ids:
            return
        if self.rules.should_ignore(ev.message):
            log.info("Ignoring comment %s (ignore_keywords)", ev.comment_id)
            return

        claimed = await self.store.claim(
            ev.comment_id,
            post_id=ev.post_id,
            from_id=ev.from_id,
            from_name=ev.from_name,
            message=ev.message,
        )
        if not claimed:
            log.info("Comment %s already processed", ev.comment_id)
            return

        result: dict[str, Any] = {
            "source": None,
            "public_reply": None,
            "private_reply": None,
            "status": "skipped",
            "error": None,
        }
        try:
            reply = await self.choose_reply(ev)
            if not reply:
                return
            result["source"] = reply.source

            # A random delay looks natural and avoids Facebook's spam heuristics.
            await asyncio.sleep(random.uniform(self.s.reply_delay_min, self.s.reply_delay_max))

            errors = []
            if reply.public:
                try:
                    await self._post_public(ev.comment_id, reply.public)
                    result["public_reply"] = reply.public
                except FacebookError as e:
                    errors.append(f"public: {e}")
            if reply.private and self.s.send_private_reply:
                try:
                    if not self.s.dry_run:
                        await self.graph.private_reply(self.s.page_id, ev.comment_id, reply.private)
                    result["private_reply"] = reply.private
                except FacebookError as e:
                    errors.append(f"private: {e}")

            if errors:
                result["status"], result["error"] = "error", "; ".join(errors)
            else:
                result["status"] = "dry_run" if self.s.dry_run else "replied"
            log.info("Comment %s [%s] -> %s", ev.comment_id, reply.source, result["status"])
        except asyncio.CancelledError:
            # Server shut down mid-delay: record that the comment was never answered.
            result["status"], result["error"] = "cancelled", "server stopped before replying"
            raise
        except Exception as e:
            log.exception("Failed to process comment %s", ev.comment_id)
            result["status"], result["error"] = "error", repr(e)
        finally:
            await self.store.finish(ev.comment_id, **result)

    async def _post_public(self, comment_id: str, message: str) -> None:
        if self.s.dry_run:
            return
        posted = await self.graph.reply_comment(comment_id, message)
        if len(self.own_comment_ids) > _MAX_OWN_IDS:
            self.own_comment_ids.clear()
        if posted.get("id"):
            self.own_comment_ids.add(posted["id"])
