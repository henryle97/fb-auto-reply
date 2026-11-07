# Bot HTTP endpoints

Every endpoint the bot serves, with its parameters, headers and responses. Responses below were
**captured from the running bot** on 2026-11-07 (ids, names and tokens replaced by
placeholders). For the Graph API calls behind them, see [facebook-api.md](facebook-api.md); for
the webhook bodies Facebook sends, see [webhook-payloads.md](webhook-payloads.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | [`/`](#get-) | none | Health check |
| `GET` | [`/webhook`](#get-webhook) | `hub.verify_token` | Facebook webhook verification |
| `POST` | [`/webhook`](#post-webhook) | `X-Hub-Signature-256` | Facebook webhook events |
| `GET` | [`/logs`](#get-logs) | `X-Admin-Token` | Recent comments and replies |
| `POST` | [`/reload-rules`](#post-reload-rules) | `X-Admin-Token` | Reload `rules.yaml` |
| `GET` | [`/posts`](#get-posts) | `X-Admin-Token` | The Page's latest posts |
| `GET` | [`/posts/find`](#get-postsfind) | `X-Admin-Token` | One post by id or URL |
| `GET` | [`/debug/payloads`](#get-debugpayloads) | `X-Admin-Token` | Last raw webhook payloads |

FastAPI also serves its generated docs at `/docs` and `/openapi.json` (no auth).

## Conventions

**Admin auth.** Admin endpoints need the header `X-Admin-Token: <FB_VERIFY_TOKEN>`. A missing
or wrong token, or an empty `FB_VERIFY_TOKEN`, gives:

```http
HTTP/1.1 403
{"detail": "Forbidden"}
```

**Errors.** Every error is JSON with a `detail` field. Errors raised by the bot have a string
`detail`. A query parameter with the wrong type or a missing required one gives FastAPI's
422 with a list:

```json
{"detail": [{"type": "int_parsing", "loc": ["query", "limit"],
             "msg": "Input should be a valid integer, unable to parse string as an integer",
             "input": "abc"}]}
```

**Ids.** Post ids are `<page id>_<post id>`. Comment ids are `<post id>_<comment id>`.

## `GET /`

Health check. Shows whether the bot posts for real and whether Claude is on.

```bash
curl https://<host>/
```

```json
{"ok": true, "dry_run": false, "ai": true}
```

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | Always `true` |
| `dry_run` | bool | `DRY_RUN`: when `true`, replies are logged, not posted |
| `ai` | bool | `AI_ENABLED`: Claude answers comments that match no rule |

## `GET /webhook`

Called by Facebook when you click **Verify and save** in the app's Webhooks settings.

| Query parameter | Value |
|---|---|
| `hub.mode` | `subscribe` |
| `hub.verify_token` | Must equal `FB_VERIFY_TOKEN` |
| `hub.challenge` | Any string; echoed back |

```bash
curl "https://<host>/webhook?hub.mode=subscribe&hub.verify_token=$FB_VERIFY_TOKEN&hub.challenge=1158201444"
```

| Status | Body |
|---|---|
| 200 `text/plain` | `1158201444` (the challenge) |
| 403 | `{"detail": "verify token mismatch"}` (wrong mode or token, or no token configured) |

## `POST /webhook`

Facebook delivers Page events here. Body: the `feed` payload described in
[webhook-payloads.md](webhook-payloads.md).

| Header | Value |
|---|---|
| `X-Hub-Signature-256` | `sha256=<hex HMAC-SHA256 of the raw body, key = FB_APP_SECRET>` |
| `Content-Type` | `application/json` |

| Status | Body | When |
|---|---|---|
| 200 | `{"ok": true}` | Valid signature. Returned immediately, before replying |
| 401 | `{"detail": "invalid signature"}` | Signature missing, malformed or wrong, or `FB_APP_SECRET` empty |

What happens after the 200, for each new comment from a person (see
[facebook-api.md → What the bot acts on](facebook-api.md#what-the-bot-acts-on)):

1. Skipped if it is the Page's own comment, or contains an `ignore_keywords` word.
2. Claimed once by `comment_id` (redelivered webhooks are ignored).
3. A reply is chosen: first matching keyword rule, otherwise Claude, otherwise the `default`
   rule when AI is off.
4. After a random `REPLY_DELAY_MIN`–`REPLY_DELAY_MAX` seconds: a public reply under the
   comment, then a Messenger message to the commenter (when `SEND_PRIVATE_REPLY=true`). See
   [facebook-api.md → Private reply](facebook-api.md#private-reply-messenger) for which inbox
   text is sent.
5. The outcome is stored and shown by [`GET /logs`](#get-logs).

When `WEBHOOK_LOG_PATH` is set, every raw payload is also appended to that file as
`{"received_at": <unix seconds>, "payload": {...}}`.

To send a test event yourself, sign the body with the app secret:

```bash
body='{"object":"page","entry":[...]}'
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$FB_APP_SECRET" | sed 's/^.* //')
curl -X POST https://<host>/webhook -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$sig" -d "$body"
```

With `DRY_RUN=false` this posts real replies, if the `comment_id` exists.

## `GET /logs`

Recent comments the bot handled, newest first.

| Query parameter | Type | Default | Notes |
|---|---|---|---|
| `limit` | int | `50` | Clamped to 1–200 |

```bash
curl -H "X-Admin-Token: $FB_VERIFY_TOKEN" "https://<host>/logs?limit=1"
```

```json
[
  {
    "comment_id": "300000000000003_400000000000004",
    "post_id": "100000000000001_300000000000003",
    "from_id": "200000000000002",
    "from_name": "Jane Doe",
    "message": "Cool <3",
    "source": "ai",
    "public_reply": "Thanks so much, Jane! 💙 We hope it helps.",
    "private_reply": "Hi Jane Doe! How can we help?",
    "status": "replied",
    "error": null,
    "created_at": 1794032995.55967
  }
]
```

| Field | Type | Meaning |
|---|---|---|
| `comment_id`, `post_id` | string | The comment and its post |
| `from_id`, `from_name` | string | The commenter |
| `message` | string | Comment text |
| `source` | string or null | Rule name, `ai` or `default`. `null` if no reply was chosen (error before, or skipped) |
| `public_reply` | string or null | Text posted (or that would be posted in dry run) under the comment |
| `private_reply` | string or null | Text sent (or that would be sent) to Messenger |
| `status` | string | See below |
| `error` | string or null | What failed; `public: ...` / `private: ...` prefixes say which post failed |
| `created_at` | float | Unix seconds when the comment was claimed |

| `status` | Meaning |
|---|---|
| `processing` | Claimed, waiting for the reply delay |
| `replied` | Posted |
| `dry_run` | Would have been posted (`DRY_RUN=true`) |
| `skipped` | No reply: Claude judged it spam, or no rule and no default applied |
| `error` | A Graph API or Claude call failed, or Claude's reply failed the output checks (length, links) |
| `cancelled` | The server stopped during the reply delay; nothing was posted |

Example error rows:

```json
{"status": "error", "source": "ai", "public_reply": "Thanks!", "private_reply": null,
 "error": "private: POST 100000000000001/messages -> 400: {...}"}
{"status": "error", "source": null, "public_reply": null, "private_reply": null,
 "error": "AIError('Claude API error 401: invalid key')"}
```

Ignored comments (the Page's own, `ignore_keywords`) are not stored.

## `POST /reload-rules`

Reloads `RULES_PATH` without restarting. No body.

```bash
curl -X POST -H "X-Admin-Token: $FB_VERIFY_TOKEN" https://<host>/reload-rules
```

```json
{"ok": true, "rules": 3}
```

`rules` is the number of keyword rules loaded. An invalid YAML file gives a 500 and the old
rules stay active. `product_info.md` is read by Claude on each call and needs no reload.

## `GET /posts`

The Page's latest posts, newest first, read live from the Graph API.

| Query parameter | Type | Default | Notes |
|---|---|---|---|
| `limit` | int | `10` | Clamped to 1–100 (Graph API page size limit) |

```bash
curl -H "X-Admin-Token: $FB_VERIFY_TOKEN" "https://<host>/posts?limit=2"
```

```json
[
  {
    "id": "100000000000001_300000000000005",
    "message": "https://example.com/s/...",
    "created_time": "2026-09-11T06:23:14+0000",
    "permalink_url": "https://www.facebook.com/100000000000009/posts/300000000000005",
    "status_type": "added_photos"
  },
  {
    "id": "100000000000001_300000000000003",
    "message": "New feature launch ...",
    "created_time": "2026-09-04T03:07:29+0000",
    "permalink_url": "https://www.facebook.com/100000000000009/posts/300000000000003",
    "status_type": "shared_story"
  }
]
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Post id, usable as `ref` in [`/posts/find`](#get-postsfind) |
| `message` | string | Post text. **Absent** for posts without text (e.g. photo only) |
| `created_time` | string | ISO 8601, `+0000` |
| `permalink_url` | string | Public link. The first number is the Page's profile id, which can differ from the Page id |
| `status_type` | string | e.g. `shared_story`, `added_photos`, `added_video`, `mobile_status_update` |

No pagination: only the newest `limit` posts. Graph's `paging` is dropped because its `next`
URL contains the access token.

| Status | Body | When |
|---|---|---|
| 502 | `{"detail": "GET <page>/posts -> 400: {...}"}` | Graph API error or network failure |

## `GET /posts/find`

One post, by id or by URL, read live from the Graph API.

| Query parameter | Required | Accepted forms |
|---|---|---|
| `ref` | yes | `100000000000001_300000000000003` (full id) |
| | | `300000000000003` (post id only; the Page id is added) |
| | | `https://www.facebook.com/<page>/posts/300000000000003` (query string ignored) |
| | | `https://www.facebook.com/permalink.php?story_fbid=300000000000003&id=<page>` (`story.php` too, any `*.facebook.com` host, scheme optional) |

URL-encode the value:

```bash
curl -G -H "X-Admin-Token: $FB_VERIFY_TOKEN" https://<host>/posts/find \
  --data-urlencode "ref=https://www.facebook.com/<page>/posts/300000000000003"
```

Response: one post with the same fields as [`/posts`](#get-posts).

```json
{
  "id": "100000000000001_300000000000003",
  "message": "New feature launch ...",
  "created_time": "2026-09-04T03:07:23+0000",
  "permalink_url": "https://www.facebook.com/100000000000009/posts/300000000000003"
}
```

`status_type` is included when Facebook returns it. `created_time` from a single-post read
was observed a few seconds earlier than in the `/posts` list for the same post.

| Status | `detail` | When |
|---|---|---|
| 400 | `expected a post id or a facebook.com post URL` | Not an id and not a Facebook URL |
| 400 | `no post id found in the URL` | A Facebook URL that is not a post link (e.g. the Page itself) |
| 400 | `pfbid share links cannot be resolved by the Graph API; ...` | `pfbid...` links (the "Share → Copy link" format). Use `/posts` instead |
| 404 | `post <id> not found: GET <id> -> 400: {... "(#10) Object does not exist ..."}` | Unknown id, a post of another Page, or a Graph/network error |
| 422 | FastAPI validation list | `ref` missing |

## `GET /debug/payloads`

The last 20 raw webhook payloads received since the server started (in memory, newest first),
including ones the bot ignored. Useful to compare what Facebook sends with
[webhook-payloads.md](webhook-payloads.md). **Contains personal data** (names, comment text).

```bash
curl -H "X-Admin-Token: $FB_VERIFY_TOKEN" https://<host>/debug/payloads
```

```json
[
  {
    "received_at": 1794032995.21,
    "payload": {"object": "page", "entry": [{"id": "100000000000001", "time": 1794032994, "changes": [...]}]}
  }
]
```

Only payloads with a valid signature are kept.
