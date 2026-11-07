import json

from fb_auto_reply.payloads import distinct, load, render

from .conftest import PAGE_ID, comment_payload


def test_distinct_anonymizes_and_dedupes(tmp_path):
    f = tmp_path / "webhooks.jsonl"
    lines = [
        {"received_at": 1.0, "payload": comment_payload(message="secret text")},
        comment_payload(comment_id="c2"),  # same shape -> collapsed
        comment_payload(from_id=PAGE_ID, verb="remove"),
    ]
    f.write_text("\n".join(json.dumps(x) for x in lines))
    items = distinct(load(f))
    assert [label for label, _ in items] == [
        "feed: item=comment verb=add",
        "feed: item=comment verb=remove (by the Page)",
    ]
    out = render(items)
    assert "secret text" not in out and "Jane" not in out and PAGE_ID not in out
    assert '"message": "<message>"' in out
