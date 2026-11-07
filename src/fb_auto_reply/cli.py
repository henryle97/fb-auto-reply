"""Command-line helpers.

fb-auto-reply check          read-only check of the Facebook setup
fb-auto-reply ask "comment"  preview the reply (rules, then Claude) without posting
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from .ai import AIError, ClaudeResponder
from .config import Settings
from .payloads import distinct, load, render
from .rules import RuleSet

REQUIRED_SCOPES = {
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_engagement",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_user_content",
}


def check(settings: Settings) -> int:
    """Verify the token, its scopes, the page subscription and a sample comment. Never writes."""
    if not settings.page_access_token or not settings.page_id:
        print("FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN must be set", file=sys.stderr)
        return 2
    base = f"https://graph.facebook.com/{settings.graph_version}"
    ok = True

    def get(path: str, **params: object) -> dict:
        params = {"access_token": settings.page_access_token, **params}
        return httpx.get(f"{base}/{path}", params=params, timeout=20).json()

    def report(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"[{'OK' if passed else 'FAIL'}] {name}{': ' + detail if detail else ''}")

    me = get("me", fields="id,name")
    if "error" in me:
        report("token", False, me["error"].get("message", str(me)))
        return 1
    report(
        "token",
        me.get("id") == settings.page_id,
        f"page '{me.get('name')}' ({me.get('id')}), FB_PAGE_ID={settings.page_id}",
    )

    info = get("debug_token", input_token=settings.page_access_token).get("data", {})
    missing = REQUIRED_SCOPES - set(info.get("scopes", []))
    report("scopes", not missing, "missing " + ", ".join(sorted(missing)) if missing else "")
    expires = info.get("expires_at")
    print(f"     token type={info.get('type')} expires={'never' if expires == 0 else expires}")

    subs = get(f"{settings.page_id}/subscribed_apps")
    if "error" in subs:
        report("subscribed_apps", False, subs["error"].get("message", ""))
    else:
        apps = subs.get("data", [])
        fields = {f for a in apps for f in a.get("subscribed_fields", [])}
        detail = f"{[a.get('name') for a in apps]} fields={sorted(fields)}" if apps else "none"
        report("subscribed_apps (feed)", "feed" in fields, detail)

    posts = get(f"{settings.page_id}/posts", fields="id", limit=5)
    for post in posts.get("data", []):
        comments = get(f"{post['id']}/comments", fields="id,message,from,created_time", limit=3)
        if comments.get("data"):
            print(json.dumps(comments["data"], ensure_ascii=False, indent=2))
            has_from = all("from" in c for c in comments["data"])
            report("comments include 'from'", has_from, "" if has_from else "names unavailable")
            break
    else:
        print("(no comments found on the 5 latest posts)")

    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


async def ask(settings: Settings, comment: str, name: str) -> int:
    rules = RuleSet.load(settings.rules_path)
    print(f"language: {rules.detect_language(comment)}")
    reply = rules.match(comment, name)
    if reply is None and settings.ai_enabled:
        responder = ClaudeResponder(settings)
        try:
            reply = await responder(comment, name, "")
        except AIError as e:
            print(f"AI error: {e}", file=sys.stderr)
            return 1
        finally:
            await responder.aclose()
    if reply is None:
        print("(no reply)")
        return 0
    print(f"source : {reply.source}\npublic : {reply.public}\nprivate: {reply.private}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fb-auto-reply")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="read-only check of the Facebook setup")
    p_ask = sub.add_parser("ask", help="preview the reply for a comment without posting")
    p_ask.add_argument("comment")
    p_ask.add_argument("--name", default="")
    p_pl = sub.add_parser("payloads", help="anonymized example of each captured payload shape")
    p_pl.add_argument("jsonl", help="file written via WEBHOOK_LOG_PATH")
    args = parser.parse_args(argv)

    if args.command == "payloads":
        print(render(distinct(load(args.jsonl))))
        return 0

    settings = Settings.from_env()
    if args.command == "check":
        return check(settings)
    return asyncio.run(ask(settings, args.comment, args.name))


if __name__ == "__main__":
    raise SystemExit(main())
