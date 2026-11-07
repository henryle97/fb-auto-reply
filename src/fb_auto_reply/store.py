"""Deduplication and reply log, backed by SQLite (default) or Supabase.

Facebook may deliver the same webhook more than once, so each comment is *claimed*
before it is processed; only the first claim succeeds.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any, Protocol

import httpx

from .config import Settings

_COLUMNS = ("source", "public_reply", "private_reply", "status", "error")


class Store(Protocol):
    async def claim(self, comment_id: str, **fields: Any) -> bool: ...
    async def finish(self, comment_id: str, **fields: Any) -> None: ...
    async def recent(self, limit: int = 50) -> list[dict[str, Any]]: ...
    async def aclose(self) -> None: ...


class SQLiteStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = asyncio.Lock()
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS processed_comments (
                comment_id TEXT PRIMARY KEY,
                post_id TEXT,
                from_id TEXT,
                from_name TEXT,
                message TEXT,
                source TEXT,
                public_reply TEXT,
                private_reply TEXT,
                status TEXT,
                error TEXT,
                created_at REAL
            )"""
        )
        self.conn.commit()

    async def claim(self, comment_id: str, **fields: Any) -> bool:
        async with self.lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO processed_comments
                   (comment_id, post_id, from_id, from_name, message, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'processing', ?)""",
                (
                    comment_id,
                    fields.get("post_id"),
                    fields.get("from_id"),
                    fields.get("from_name"),
                    fields.get("message"),
                    time.time(),
                ),
            )
            self.conn.commit()
            return cur.rowcount == 1

    async def finish(self, comment_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{c} = ?" for c in _COLUMNS)
        async with self.lock:
            self.conn.execute(
                f"UPDATE processed_comments SET {assignments} WHERE comment_id = ?",  # noqa: S608
                [fields.get(c) for c in _COLUMNS] + [comment_id],
            )
            self.conn.commit()

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.lock:
            cur = self.conn.execute(
                "SELECT * FROM processed_comments ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    async def aclose(self) -> None:
        self.conn.close()


class SupabaseStore:
    """Supabase via PostgREST. Create the table with supabase_schema.sql."""

    def __init__(self, url: str, key: str, http: httpx.AsyncClient | None = None):
        self.base = f"{url.rstrip('/')}/rest/v1/processed_comments"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self.http = http or httpx.AsyncClient(timeout=15.0)

    async def claim(self, comment_id: str, **fields: Any) -> bool:
        row = {"comment_id": comment_id, "status": "processing", **fields}
        r = await self.http.post(
            self.base,
            headers={
                **self.headers,
                "Prefer": "resolution=ignore-duplicates,return=representation",
            },
            content=json.dumps(row),
        )
        r.raise_for_status()
        return len(r.json()) == 1  # duplicate key -> [] -> already processed

    async def finish(self, comment_id: str, **fields: Any) -> None:
        r = await self.http.patch(
            self.base,
            params={"comment_id": f"eq.{comment_id}"},
            headers=self.headers,
            content=json.dumps({c: fields.get(c) for c in _COLUMNS}),
        )
        r.raise_for_status()

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        r = await self.http.get(
            self.base, params={"order": "created_at.desc", "limit": limit}, headers=self.headers
        )
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self.http.aclose()


def make_store(settings: Settings) -> Store:
    if settings.supabase_url and settings.supabase_key:
        return SupabaseStore(settings.supabase_url, settings.supabase_key)
    return SQLiteStore(settings.sqlite_path)
