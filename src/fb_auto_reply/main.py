"""FastAPI app: Facebook webhook plus a few admin endpoints.

Run with: uvicorn fb_auto_reply.main:create_app --factory --port 7860
"""

from __future__ import annotations

import asyncio
import collections
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .ai import ClaudeResponder
from .config import Settings
from .facebook import FacebookError, GraphClient, parse_post_ref, verify_signature
from .processor import Generate, Graph, Processor, extract_comment_events
from .rules import RuleSet
from .store import Store, make_store

log = logging.getLogger("fb_auto_reply")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # httpx logs full URLs at INFO, and Graph API calls carry the access token in the query.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def create_app(
    settings: Settings | None = None,
    *,
    graph: Graph | None = None,
    store: Store | None = None,
    generate: Generate | None = None,
) -> FastAPI:
    _configure_logging()
    settings = settings or Settings.from_env()
    graph = graph or GraphClient(settings.page_access_token, settings.graph_version)
    store = store or make_store(settings)
    responder = None
    if generate is None and settings.ai_enabled:
        generate = responder = ClaudeResponder(settings)
    processor = Processor(settings, RuleSet.load(settings.rules_path), graph, store, generate)
    tasks: set[asyncio.Task[None]] = set()
    # Last webhook payloads, to compare what Facebook really sends with what the code expects.
    recent_payloads: collections.deque[dict[str, Any]] = collections.deque(maxlen=20)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info(
            "Started: page=%s dry_run=%s ai=%s rules=%s",
            settings.page_id,
            settings.dry_run,
            settings.ai_enabled,
            settings.rules_path,
        )
        yield
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for resource in (graph, store, responder):
            if resource is not None and hasattr(resource, "aclose"):
                await resource.aclose()

    app = FastAPI(title="fb-auto-reply", lifespan=lifespan)

    def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
        token = settings.verify_token
        if not token or not x_admin_token or not hmac.compare_digest(x_admin_token, token):
            raise HTTPException(403)

    admin = [Depends(require_admin)]

    @app.get("/")
    async def health() -> dict[str, Any]:
        return {"ok": True, "dry_run": settings.dry_run, "ai": settings.ai_enabled}

    @app.get("/webhook")
    async def verify(
        mode: Annotated[str, Query(alias="hub.mode")] = "",
        token: Annotated[str, Query(alias="hub.verify_token")] = "",
        challenge: Annotated[str, Query(alias="hub.challenge")] = "",
    ) -> PlainTextResponse:
        """Called by Facebook when you click "Verify and save" in the Webhooks settings."""
        expected = settings.verify_token
        if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
            return PlainTextResponse(challenge)
        raise HTTPException(403, "verify token mismatch")

    @app.post("/webhook")
    async def receive(
        request: Request,
        x_hub_signature_256: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        body = await request.body()
        if not verify_signature(body, x_hub_signature_256, settings.app_secret):
            raise HTTPException(401, "invalid signature")

        # Anything that is signed but unusable is acknowledged with 200 and ignored: a non-200
        # makes Facebook retry for up to 36 hours and unsubscribe the app after 1 hour of
        # failures, and a retry of the same body would fail the same way.
        try:
            payload = json.loads(body)
        except ValueError:
            log.warning("Ignoring webhook with invalid JSON body: %r", body[:200])
            return {"ok": True}
        if not isinstance(payload, dict):
            log.warning("Ignoring webhook whose body is not a JSON object")
            return {"ok": True}
        received = {"received_at": time.time(), "payload": payload}
        recent_payloads.appendleft(received)
        log.debug("Webhook payload: %s", body.decode(errors="replace")[:2000])
        if settings.webhook_log_path:
            await asyncio.to_thread(_append_jsonl, settings.webhook_log_path, received)
        try:
            events = extract_comment_events(payload, settings.page_id)
        except (AttributeError, TypeError, KeyError):
            log.warning("Ignoring webhook with an unexpected shape: %s", str(payload)[:500])
            return {"ok": True}
        for ev in events:
            # Answer 200 immediately (Facebook retries slow webhooks); reply in the background.
            task = asyncio.create_task(processor.handle(ev))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return {"ok": True}

    @app.post("/reload-rules", dependencies=admin)
    async def reload_rules() -> dict[str, Any]:
        """Reload rules.yaml without restarting."""
        processor.rules = RuleSet.load(settings.rules_path)
        return {"ok": True, "rules": len(processor.rules.rules)}

    @app.get("/logs", dependencies=admin)
    async def logs(limit: int = 50) -> list[dict[str, Any]]:
        return await store.recent(max(1, min(limit, 200)))

    @app.get("/posts", dependencies=admin)
    async def posts(limit: int = 10) -> list[dict[str, Any]]:
        """The Page's last `limit` posts (1-100), newest first."""
        try:
            return await graph.list_posts(settings.page_id, limit)
        except FacebookError as e:
            raise HTTPException(502, str(e)) from e

    @app.get("/posts/find", dependencies=admin)
    async def find_post(ref: str) -> dict[str, Any]:
        """One post by id (`PAGEID_POSTID` or `POSTID`) or by its facebook.com URL."""
        try:
            post_id = parse_post_ref(ref, settings.page_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        try:
            return await graph.get_post(post_id)
        except FacebookError as e:
            raise HTTPException(404, f"post {post_id} not found: {e}") from e

    @app.get("/debug/payloads", dependencies=admin)
    async def debug_payloads() -> list[dict[str, Any]]:
        return list(recent_payloads)

    app.state.processor = processor
    return app
