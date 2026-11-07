"""Facebook Graph API client and webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

log = logging.getLogger(__name__)


class FacebookError(Exception):
    """A Graph API call failed."""


POST_FIELDS = "id,message,created_time,permalink_url,status_type"
MAX_POSTS = 100  # Graph API page size limit for /{page_id}/posts

_FULL_ID = re.compile(r"\d+_\d+")
_POSTS_PATH = re.compile(r"/posts/(\w+)")


def parse_post_ref(ref: str, page_id: str) -> str:
    """Turn a post id or a Facebook post URL into a Graph API post id (`{page_id}_{post}`).

    Accepts `PAGEID_POSTID`, a bare `POSTID`, `facebook.com/<page>/posts/<POSTID>` and
    `facebook.com/permalink.php?story_fbid=<POSTID>&id=<page>`. Raises ValueError otherwise.
    The Graph API rejects bare post ids (#12), so they are prefixed with the Page id.
    """
    ref = ref.strip()
    if _FULL_ID.fullmatch(ref):
        return ref
    if ref.isdigit():
        return f"{page_id}_{ref}"
    if "facebook.com" not in ref and "fb.com" not in ref:
        raise ValueError("expected a post id or a facebook.com post URL")
    url = urlsplit(ref if "://" in ref else f"https://{ref}")
    post = None
    if m := _POSTS_PATH.search(url.path):
        post = m.group(1)
    elif url.path.rstrip("/") in ("/permalink.php", "/story.php"):
        post = parse_qs(url.query).get("story_fbid", [""])[0]
    if post and post.isdigit():
        return f"{page_id}_{post}"
    if post and post.startswith("pfbid"):
        raise ValueError(
            "pfbid share links cannot be resolved by the Graph API; "
            "use GET /posts to find the post, or copy the link from the post's timestamp"
        )
    raise ValueError("no post id found in the URL")


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
        try:
            r = await self.http.request(method, f"{self.base}/{path}", params=params, **kwargs)
        except httpx.HTTPError as e:
            # Network failures (timeouts, TLS errors) are Graph API failures too, so callers
            # that tolerate FacebookError (e.g. reading the post text) keep going.
            raise FacebookError(f"{method} {path} -> {type(e).__name__}: {e}") from e
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

    async def list_posts(self, page_id: str, limit: int) -> list[dict[str, Any]]:
        """The Page's latest posts, newest first (at most MAX_POSTS)."""
        params = {"fields": POST_FIELDS, "limit": max(1, min(limit, MAX_POSTS))}
        data = await self._request("GET", f"{page_id}/posts", params=params)
        # Drop `paging`: its `next` URL embeds the access token.
        return data.get("data", [])

    async def get_post(self, post_id: str) -> dict[str, Any]:
        return await self._request("GET", post_id, params={"fields": POST_FIELDS})

    async def get_post_text(self, post_id: str) -> str:
        try:
            data = await self._request("GET", post_id, params={"fields": "message"})
        except FacebookError as e:
            log.info("Could not read post %s: %s", post_id, e)
            return ""
        return data.get("message", "")
