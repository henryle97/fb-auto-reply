import hashlib
import hmac
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fb_auto_reply.config import Settings
from fb_auto_reply.facebook import FacebookError
from fb_auto_reply.processor import CommentEvent, Processor
from fb_auto_reply.rules import Reply, RuleSet
from fb_auto_reply.store import SQLiteStore

PAGE_ID = "100000000000001"
# A frozen copy of the example rules, so editing the examples does not break the tests.
RULES = Path(__file__).parent / "rules.yaml"


def sign(body: bytes, secret: str = "secret") -> str:  # noqa: S107
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def comment_payload(
    from_id: str = "200000000000002",
    verb: str = "add",
    message: str = "How much does it cost?",
    comment_id: str = "c1",
) -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": verb,
                            "comment_id": comment_id,
                            "post_id": "p1",
                            "from": {"id": from_id, "name": "Jane"},
                            "message": message,
                        },
                    }
                ],
            }
        ],
    }


class FakeGraph:
    def __init__(self, fail_private: bool = False, reply_id: str = "bot1"):
        self.reply_id = reply_id
        self.fail_private = fail_private
        self.calls: list[tuple[str, str, str]] = []

    async def reply_comment(self, comment_id: str, message: str) -> dict[str, Any]:
        self.calls.append(("public", comment_id, message))
        return {"id": self.reply_id}

    async def private_reply(self, page_id: str, comment_id: str, message: str) -> None:
        if self.fail_private:
            raise FacebookError("window expired")
        self.calls.append(("private", comment_id, message))

    async def get_post_text(self, post_id: str) -> str:
        return "New feature launch"

    async def list_posts(self, page_id: str, limit: int) -> list[dict[str, Any]]:
        posts = [{"id": f"{page_id}_{n}", "message": f"post {n}"} for n in range(3, 0, -1)]
        return posts[:limit]

    async def get_post(self, post_id: str) -> dict[str, Any]:
        if not post_id.endswith("_3"):
            raise FacebookError(f"GET {post_id} -> 400: Object does not exist")
        return {"id": post_id, "message": "post 3"}


class FakeAI:
    def __init__(self, result: Reply | Exception | None = None):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, comment: str, name: str, post_text: str) -> Reply | None:
        self.calls.append((comment, post_text))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def rules() -> RuleSet:
    return RuleSet.load(RULES)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(
        Settings(),
        page_id=PAGE_ID,
        app_secret="secret",
        verify_token="vt",
        dry_run=False,
        ai_enabled=True,
        send_private_reply=True,
        reply_delay_min=0,
        reply_delay_max=0,
        sqlite_path=str(tmp_path / "test.db"),
        rules_path=str(RULES),
    )


@pytest.fixture
def make_processor(settings: Settings, rules: RuleSet):
    def make(ai: FakeAI | None = None) -> tuple[Processor, FakeGraph, SQLiteStore, FakeAI]:
        ai = ai or FakeAI()
        graph = FakeGraph()
        store = SQLiteStore(settings.sqlite_path)
        return Processor(settings, rules, graph, store, ai), graph, store, ai

    return make


def event(message: str, comment_id: str = "c1") -> CommentEvent:
    return CommentEvent(comment_id, "p1", "200000000000002", "Jane", message)
