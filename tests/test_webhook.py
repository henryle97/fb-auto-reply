import json

from fastapi.testclient import TestClient

from fb_auto_reply.facebook import verify_signature
from fb_auto_reply.main import create_app
from fb_auto_reply.store import SQLiteStore

from .conftest import FakeAI, FakeGraph, comment_payload, sign


def test_verify_signature():
    body = b'{"a":1}'
    assert verify_signature(body, sign(body), "secret")
    assert not verify_signature(body, sign(body), "other")
    assert not verify_signature(body, None, "secret")
    assert not verify_signature(body, sign(body, ""), "")  # no secret configured


def make_client(settings):
    app = create_app(
        settings, graph=FakeGraph(), store=SQLiteStore(settings.sqlite_path), generate=FakeAI()
    )
    return TestClient(app)


def test_webhook_verification(settings):
    with make_client(settings) as client:
        params = {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}
        r = client.get("/webhook", params=params)
        assert r.status_code == 200 and r.text == "42"
        params["hub.verify_token"] = "wrong"
        assert client.get("/webhook", params=params).status_code == 403


def test_webhook_requires_signature(settings):
    body = json.dumps(comment_payload()).encode()
    with make_client(settings) as client:
        assert client.post("/webhook", content=body).status_code == 401
        headers = {"X-Hub-Signature-256": sign(body)}
        assert client.post("/webhook", content=body, headers=headers).status_code == 200


def test_admin_endpoints_need_token(settings):
    with make_client(settings) as client:
        assert client.get("/logs").status_code == 403
        assert client.get("/logs", headers={"X-Admin-Token": "nope"}).status_code == 403
        assert client.get("/logs", headers={"X-Admin-Token": "vt"}).status_code == 200
        r = client.post("/reload-rules", headers={"X-Admin-Token": "vt"})
        assert r.json() == {"ok": True, "rules": 3}


def test_posts_endpoints(settings):
    headers = {"X-Admin-Token": "vt"}
    page = settings.page_id
    with make_client(settings) as client:
        assert client.get("/posts").status_code == 403
        r = client.get("/posts", params={"limit": 2}, headers=headers)
        assert [p["id"] for p in r.json()] == [f"{page}_3", f"{page}_2"]

        url = "https://www.facebook.com/122131032267466171/posts/3?substory_index=3"
        for ref in (f"{page}_3", "3", url):
            r = client.get("/posts/find", params={"ref": ref}, headers=headers)
            assert r.status_code == 200 and r.json()["id"] == f"{page}_3", ref
        assert client.get("/posts/find", params={"ref": "9"}, headers=headers).status_code == 404
        bad = client.get("/posts/find", params={"ref": "hello"}, headers=headers)
        assert bad.status_code == 400


def test_signed_but_unusable_bodies_are_acknowledged(settings):
    # A non-200 makes Facebook retry for hours and eventually unsubscribe the app.
    bodies = [
        b"not json",
        b"[]",
        b"{}",
        json.dumps({"object": "page", "entry": "oops"}).encode(),
        json.dumps(
            {"object": "page", "entry": [{"changes": [{"field": "feed", "value": 1}]}]}
        ).encode(),
        json.dumps({"object": "page", "entry": [{"changes": [{"field": "messages"}]}]}).encode(),
    ]
    with make_client(settings) as client:
        for body in bodies:
            r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
            assert (r.status_code, r.json()) == (200, {"ok": True}), body
