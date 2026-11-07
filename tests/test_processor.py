import asyncio
import json

from fb_auto_reply.ai import AIError
from fb_auto_reply.processor import extract_comment_events
from fb_auto_reply.rules import Reply

from .conftest import PAGE_ID, FakeAI, FakeGraph, comment_payload, event

# Shape of a real `feed` webhook (Graph API v27.0), with IDs and names anonymized.
CAPTURED_PAYLOAD = {
    "entry": [
        {
            "id": PAGE_ID,
            "time": 1794026898,
            "changes": [
                {
                    "value": {
                        "from": {"id": "200000000000002", "name": "Jane Doe"},
                        "post": {
                            "status_type": "shared_story",
                            "is_published": True,
                            "id": f"{PAGE_ID}_300000000000003",
                        },
                        "message": "Cool <3",
                        "post_id": f"{PAGE_ID}_300000000000003",
                        "comment_id": "300000000000003_400000000000004",
                        "created_time": 1794026895,
                        "item": "comment",
                        "parent_id": f"{PAGE_ID}_300000000000003",
                        "verb": "add",
                    },
                    "field": "feed",
                }
            ],
        }
    ],
    "object": "page",
}


def test_extract_skips_own_edits_and_empty():
    assert len(extract_comment_events(comment_payload(), PAGE_ID)) == 1
    assert extract_comment_events(comment_payload(from_id=PAGE_ID), PAGE_ID) == []
    assert extract_comment_events(comment_payload(verb="edited"), PAGE_ID) == []
    assert extract_comment_events(comment_payload(message="  "), PAGE_ID) == []


def test_extract_captured_payload():
    (ev,) = extract_comment_events(CAPTURED_PAYLOAD, PAGE_ID)
    assert ev.comment_id == "300000000000003_400000000000004"
    assert ev.post_id == f"{PAGE_ID}_300000000000003"
    assert (ev.from_name, ev.message) == ("Jane Doe", "Cool <3")

    removed = json.loads(json.dumps(CAPTURED_PAYLOAD))
    removed["entry"][0]["changes"][0]["value"]["verb"] = "remove"
    assert extract_comment_events(removed, PAGE_ID) == []


async def test_rule_reply_and_dedup(make_processor):
    p, graph, store, ai = make_processor()
    await p.handle(event("how much is it?"))
    await p.handle(event("how much is it?"))  # webhook redelivered -> no second reply
    assert [c[0] for c in graph.calls] == ["public", "private"]
    assert ai.calls == []
    row = (await store.recent())[0]
    assert (row["status"], row["source"]) == ("replied", "pricing")


async def test_dry_run_posts_nothing(make_processor):
    from dataclasses import replace

    p, graph, store, _ = make_processor()
    p.s = replace(p.s, dry_run=True)
    await p.handle(event("how much is it?"))
    assert graph.calls == []
    assert (await store.recent())[0]["status"] == "dry_run"


async def test_ai_fallback(make_processor):
    p, graph, _, ai = make_processor(FakeAI(Reply("AI public", "AI private", "ai")))
    await p.handle(event("does it work offline?"))
    assert ai.calls == [("does it work offline?", "New feature launch")]
    assert graph.calls == [("public", "c1", "AI public"), ("private", "c1", "AI private")]


async def test_ai_declines_spam(make_processor):
    p, graph, store, _ = make_processor(FakeAI(None))
    await p.handle(event("@Mike look at this"))
    assert graph.calls == []
    assert (await store.recent())[0]["status"] == "skipped"


async def test_ai_error_is_recorded(make_processor):
    p, graph, store, _ = make_processor(FakeAI(AIError("Claude API error 401: invalid key")))
    await p.handle(event("does it work offline?"))
    row = (await store.recent())[0]
    assert graph.calls == []
    assert row["status"] == "error" and "401" in row["error"]


async def test_private_failure_keeps_public(make_processor):
    p, _, store, _ = make_processor()
    p.graph = FakeGraph(fail_private=True)
    await p.handle(event("how much is it?"))
    row = (await store.recent())[0]
    assert row["status"] == "error" and row["public_reply"] and "window expired" in row["error"]


async def test_ignores_own_reply(make_processor):
    p, graph, _, _ = make_processor()
    await p.handle(event("dm me", comment_id="c1"))
    n = len(graph.calls)
    # Webhook for the bot's own reply arriving without from.id must be ignored.
    await p.handle(event("Hi Jane, we've just sent you a message.", comment_id="bot1"))
    assert len(graph.calls) == n


async def test_cancelled_is_recorded(make_processor):
    from dataclasses import replace

    p, _, store, _ = make_processor()
    p.s = replace(p.s, reply_delay_min=10, reply_delay_max=10)
    task = asyncio.create_task(p.handle(event("how much is it?")))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert (await store.recent())[0]["status"] == "cancelled"


def test_ai_output_checks():
    import pytest

    from fb_auto_reply.ai import check_reply

    hosts = {"example.com"}
    assert check_reply("See https://example.com/pricing", 500, hosts, "f") is not None
    assert check_reply("Try www.example.com/x or example.com/y", 500, hosts, "f")
    assert check_reply("Sign up at https://example.com.", 500, hosts, "f")
    assert check_reply("  ", 500, hosts, "f") is None
    assert check_reply("Download lesson.html, e.g. on a phone. Costs 1.5 gold.", 500, hosts, "f")
    bad_replies = [
        "Win at https://evil.test/x",
        "go to evil.test/login",
        "visit evil.test now",
        "see sub.evil.test.",
        "x" * 501,
    ]
    for bad in bad_replies:
        with pytest.raises(AIError):
            check_reply(bad, 500, hosts, "f")
