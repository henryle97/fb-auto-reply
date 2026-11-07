"""Facebook Graph API client and webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class FacebookError(Exception):
    """A Graph API call failed."""


def verify_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Check the X-Hub-Signature-256 header so only Facebook can call the webhook."""
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


class GraphClient:
    def __init__(self, token: str, version: str, http: httpx.AsyncClient | None = None):
        self.token = token
        self.base = f"https://graph.facebook.com/{version}"
        self.http = http or httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        params = {"access_token": self.token, **kwargs.pop("params", {})}
        r = await self.http.request(method, f"{self.base}/{path}", params=params, **kwargs)
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in data:
            raise FacebookError(f"{method} {path} -> {r.status_code}: {data.get('error', data)}")
        return data

    async def reply_comment(self, comment_id: str, message: str) -> dict[str, Any]:
        return await self._request("POST", f"{comment_id}/comments", json={"message": message})

    async def private_reply(self, page_id: str, comment_id: str, message: str) -> dict[str, Any]:
        """Send a Messenger message to the commenter (once per comment, within 7 days)."""
        return await self._request(
            "POST",
            f"{page_id}/messages",
            json={"recipient": {"comment_id": comment_id}, "message": {"text": message}},
        )

    async def get_post_text(self, post_id: str) -> str:
        try:
            data = await self._request("GET", post_id, params={"fields": "message"})
        except FacebookError as e:
            log.info("Could not read post %s: %s", post_id, e)
            return ""
        return data.get("message", "")
