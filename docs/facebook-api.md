# Facebook API reference

This page describes every Facebook (Meta Graph API) interaction the bot depends on. The bot's
own HTTP endpoints are in [endpoints.md](endpoints.md). Behaviour marked **verified** was observed against the live API
on 2026-11-07. Everything else follows Meta's documentation, linked at the end.

## Versions

There are two independent version numbers:

| What | Where it is set | Value used | Effect |
|---|---|---|---|
| Outgoing Graph API calls | `FB_GRAPH_VERSION`, sent in every URL (`/v25.0/...`) | `v25.0` | Request and response format of the calls below |
| Webhook payloads | App Dashboard → Webhooks → Page → field `feed` → version | `v27.0` (the only choice for new apps) | Shape of the JSON Facebook POSTs to `/webhook` |

The app's default API version (App settings → Advanced) applies only to calls made
**without** a version in the URL. The bot never makes such calls, so it does not matter.

Mixing versions is fine. Calls at v25.0 and webhooks at v27.0 is the verified setup.

Each Graph API version is supported for about two years. According to Meta's changelog,
v25.0 is available until **2028-07-29**. After that, calls are automatically upgraded to the
oldest supported version. Bump `FB_GRAPH_VERSION` before then and re-run the tests.

## Permissions

The Page access token needs these permissions:

| Permission | Needed for |
|---|---|
| `pages_show_list` | Finding the Page via `/me/accounts` |
| `pages_manage_metadata` | Subscribing the app to the Page (`subscribed_apps`) |
| `pages_read_engagement` | Reading posts and comments |
| `pages_read_user_content` | Getting `from` (commenter id and name) in comments |
| `pages_manage_engagement` | Replying to comments |
| `pages_messaging` | Private replies (Messenger) |

`fb-auto-reply check` prints the token's scopes and reports any that are missing.

> **Verified:** while the app was in **Development** mode, real comments did not produce
> `feed` webhooks. Publishing the app (Live mode) fixed it.

## Outgoing calls

Base URL: `https://graph.facebook.com/{FB_GRAPH_VERSION}`. The Page access token is sent as
the `access_token` query parameter. Errors come back as HTTP 4xx with a JSON body, raised as
`FacebookError`. Every code and message is listed under [Errors](#errors).

### Reply to a comment (public)

```http
POST /{comment_id}/comments
Content-Type: application/json

{"message": "Thanks for your interest!"}
```

Response (**verified**):

```json
{"id": "300000000000003_500000000000005"}
```

The reply is posted as the Page. The returned id is remembered so the bot never answers its
own reply. Facebook also sends a webhook for it, with `from.id` equal to the Page id.

### Private reply (Messenger)

```http
POST /{page_id}/messages
Content-Type: application/json

{"recipient": {"comment_id": "300000000000003_400000000000004"},
 "message": {"text": "Hi! Here are the details..."}}
```

Response (from Meta's docs; the bot does not store it):

```json
{"recipient_id": "...", "message_id": "m_..."}
```

Limits: **one** private reply per comment, within **7 days** of the comment. After that, the
call fails. The bot keeps the public reply and records the error. Error codes:
[Private reply limits](#private-reply-limits-docs).

Which text is sent:

| Reply source | Inbox message |
|---|---|
| Keyword rule | The rule's `private_reply`. A rule without one sends no inbox message. |
| Claude | Claude's `private_message`. Claude leaves it empty for thanks and compliments; the `default.private_reply` template from `rules.yaml` (in the commenter's language) is sent instead. |
| Default (AI off) | `default.private_reply` |
| Claude declined (spam) | Nothing, and no public reply either |

`SEND_PRIVATE_REPLY=false` turns inbox messages off entirely. The message arrives in the
commenter's Messenger, often under **Message requests** if they never chatted with the Page.
The comment must come from a person: comments posted as the Page are ignored.

### Read a post's text

Gives the AI context on what the comment is replying to:

```http
GET /{post_id}?fields=message
```

```json
{"message": "New feature launch ...", "id": "100000000000001_300000000000003"}
```

Failures (including network timeouts) are logged and ignored; the AI then answers without
post context.

### List and look up posts (admin endpoints)

Used by [`GET /posts` and `GET /posts/find`](endpoints.md#get-posts). Response shapes **verified** on v25.0.

```http
GET /{page_id}/posts?fields=id,message,created_time,permalink_url,status_type&limit={k}
```

```json
{"data": [{"id": "100000000000001_300000000000003", "message": "New feature launch ...",
           "created_time": "2026-09-04T03:07:29+0000",
           "permalink_url": "https://www.facebook.com/100000000000009/posts/300000000000003",
           "status_type": "shared_story"}],
 "paging": {"cursors": {...}, "next": "https://graph.facebook.com/...&access_token=..."}}
```

`limit` is capped at 100. `message` is missing for posts without text (e.g. photo-only).
The bot drops `paging` because `paging.next` contains the access token.

```http
GET /{page_id}_{post_id}?fields=id,message,created_time,permalink_url,status_type
```

Post lookup findings (**verified**):

- A bare post id (`GET /300000000000003`) fails with `(#12) singular statuses API is
  deprecated`. The id must be `{page_id}_{post_id}`, so the bot adds the Page id.
- On pages using the new Pages experience, the number in `permalink_url`
  (`facebook.com/<profile id>/posts/<post_id>`) is a different id from the Page id. Only the
  `<post_id>` part is used.
- `GET /?id=<post url>` does not resolve post URLs; it echoes the URL back as `id`.
- A post that does not exist returns `(#10) Object does not exist, cannot be loaded due to
  missing permission ...`.
- `pfbid...` share links (e.g. `permalink.php?story_fbid=pfbid0...`, also seen in webhook
  `post.permalink_url`) cannot be turned into a post id. Use `GET /posts` to find the post.

### Setup and diagnostics calls

These are used by `fb-auto-reply check` or during setup, never while handling comments.

| Call | Purpose |
|---|---|
| `GET /me?fields=id,name` | Which Page the token belongs to |
| `GET /debug_token?input_token={token}` | Token type, scopes, expiry (`expires_at: 0` = never) |
| `GET /{page_id}/subscribed_apps` | Apps subscribed to the Page, with `subscribed_fields` |
| `POST /{page_id}/subscribed_apps?subscribed_fields=feed` | Subscribe the app to the Page's `feed` |
| `POST /{app_id}/subscriptions` (app token `app_id\|app_secret`) with `object=page`, `callback_url`, `fields=feed`, `verify_token` | Register or change the webhook URL from the command line, e.g. when a tunnel URL changes |
| `GET /{page_id}/posts?fields=id` and `GET /{post_id}/comments?fields=id,message,from,created_time` | Sample real comments |
| `GET /oauth/access_token?grant_type=fb_exchange_token&...` | Exchange a short-lived user token for a long-lived one |
| `GET /me/accounts` (user token) | List Pages and their Page tokens |

## Incoming webhooks

### Verification: `GET /webhook`

When you click "Verify and save", Facebook calls:

```
GET /webhook?hub.mode=subscribe&hub.verify_token=<FB_VERIFY_TOKEN>&hub.challenge=1158201444
```

The bot returns the `hub.challenge` value as plain text when the token matches. Otherwise it
returns 403. `hub.mode` is always `subscribe`; `hub.challenge` is an integer in Meta's docs,
returned as-is. The callback URL must be HTTPS with a certificate from a public CA:
self-signed certificates are rejected (Cloudflare tunnels and HF Spaces both qualify).

### Events: `POST /webhook`

Full schema and every captured payload: [webhook-payloads.md](webhook-payloads.md).

Every event is signed with the app secret:

```
X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw request body, key = FB_APP_SECRET>
```

The HMAC is computed over the **raw body bytes** exactly as received. Facebook sends
non-ASCII text as `\uXXXX` escapes (verified: names like `Ho\u00e0ng` arrive escaped), so
re-serialising the parsed JSON would produce different bytes and a wrong signature. Only
`X-Hub-Signature-256` is checked; the older SHA-1 `X-Hub-Signature` is not used.

Requests with a missing or invalid signature get 401. Valid ones get 200 immediately, and
replies happen in the background.

### Delivery, retries and failures

From Meta's docs, with the bot's behaviour for each:

| Facebook behaviour (docs) | What the bot does |
|---|---|
| Expects **200** for every event, within **5 seconds** (Messenger webhook docs) | Answers 200 before doing any work; replies run in the background |
| A failed or unacknowledged delivery is retried immediately, then with decreasing frequency for up to **36 hours**, then dropped | Same comment may arrive again: deduplicated by `comment_id` (SQLite or Supabase). Use Supabase on hosts that lose their disk, or a redelivery after a restart is answered twice |
| After **15 minutes** of failures: developer alert. After **1 hour**: "Webhooks Disabled" alert and the **app is unsubscribed from the Page** | Must re-run `POST /{page_id}/subscribed_apps?subscribed_fields=feed` (README step 4). A free HF Space that sleeps or crashes for over an hour hits this; check with `fb-auto-reply check` |
| Up to **1000** changes per request, batching not guaranteed; delivery order not guaranteed | Loops over every `entry` and `change`; order does not matter because each comment is handled on its own |
| Duplicates possible; "your server should handle deduplication" | Claim-once by `comment_id` |
| Delivered only if the Page installed the app and has not turned off the app platform | `fb-auto-reply check` shows `subscribed_apps` |
| Events from people without an app role need **Advanced Access** (App Review) and a published app | Verified: in Development mode no real `feed` webhooks arrived; Live mode fixed it |
| Not sent for Ad Posts themselves, but sent for comments on Ad Posts | Comments on ads are answered like any other |

Bot responses to `POST /webhook` (see [endpoints.md](endpoints.md#post-webhook)):

| Request | Response |
|---|---|
| Missing, malformed or wrong signature | 401 (Facebook retries; only matters if `FB_APP_SECRET` is wrong, which also triggers the 1-hour unsubscribe) |
| Signed, any JSON object (including other `object` values, other fields, unknown items) | 200 `{"ok": true}`; non-comment events are ignored |
| Signed, but not JSON, not an object, or an unexpected shape | 200 `{"ok": true}` and a warning in the log. Acknowledged on purpose: a retry of the same body cannot succeed, and repeated failures unsubscribe the app |

Not documented by Meta: maximum payload size, and whether the 5-second limit also applies to
`feed` events (it is stated on the Messenger webhook page, which covers Page webhooks in
general).

#### New comment (`verb: add`), verified, v27.0, ids anonymized

```json
{
  "object": "page",
  "entry": [
    {
      "id": "100000000000001",
      "time": 1794026898,
      "changes": [
        {
          "field": "feed",
          "value": {
            "item": "comment",
            "verb": "add",
            "comment_id": "300000000000003_400000000000004",
            "post_id": "100000000000001_300000000000003",
            "parent_id": "100000000000001_300000000000003",
            "created_time": 1794026895,
            "message": "Cool <3",
            "from": {"id": "200000000000002", "name": "Jane Doe"},
            "post": {
              "id": "100000000000001_300000000000003",
              "status_type": "shared_story",
              "is_published": true
            }
          }
        }
      ]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `entry[].id` | Page id |
| `value.item` | What changed: `comment`, and also `reaction`, `status`, `photo`, `post`, ... |
| `value.verb` | `add`, `edited`, `remove` (also `hide`, `unhide` per docs) |
| `value.comment_id` | Id to reply to |
| `value.post_id` | Post the comment belongs to |
| `value.parent_id` | The post id for a top-level comment; the parent comment id for a reply in a thread |
| `value.from` | Commenter. Requires `pages_read_user_content` and an app in Live mode; may be missing otherwise |
| `value.message` | Comment text. Empty or missing for photo/sticker-only comments |

#### Deleted comment (`verb: remove`), verified

The same shape as above with `"verb": "remove"`, sent when a comment is deleted.

#### What the bot acts on

`extract_comment_events` keeps a change only if **all** of these hold:

- `object == "page"` and `field == "feed"`
- `item == "comment"` and `verb == "add"` (edits, removals, reactions and posts are ignored)
- `from.id` is not the Page id (skips the Page's own comments, including the bot's replies)
- `comment_id` is present and `message` is not blank

`GET /debug/payloads` returns the last 20 raw payloads, to compare with this page when
Facebook changes something.

## Errors

Everything a caller needs to handle Graph API failures without probing the live API.
**Verified** rows were returned by the live API (v25.0) on 2026-11-07 with this bot's Page
token. **Docs** rows come from Meta's documentation (links in [Sources](#sources)) and could
not be reproduced safely, because triggering them means messaging real people, revoking the
token, or exhausting rate limits.

### Error body

```json
{
  "error": {
    "message": "Invalid parameter",
    "type": "OAuthException",
    "code": 100,
    "error_subcode": 1893060,
    "is_transient": false,
    "error_user_title": "Invalid private reply comment ID",
    "error_user_msg": "The comment_id provided (1) is not valid. ...",
    "fbtrace_id": "A_FkNBRR4_8WUapEkUb5VZe"
  }
}
```

| Field | Always present | Meaning |
|---|---|---|
| `message` | yes | Developer-facing text. Often starts with `(#<code>)` |
| `type` | yes | `OAuthException` for almost everything; `GraphMethodException` for unsupported GETs (seen with `100`/`33`) |
| `code` | yes | Main error code; branch on this |
| `error_subcode` | no | Refines `code`. Branch on `(code, error_subcode)` when present |
| `is_transient` | no | `true` means retrying the same call may succeed. Seen only on Messenger (`/messages`) errors; not described in Meta's docs |
| `error_user_title`, `error_user_msg` | no | Human-readable title and text, in the request's locale. Seen on Messenger errors |
| `fbtrace_id` | yes | Support id for Meta bug reports. Short-lived |

Headers (**verified**):

- The HTTP status is **400** for every error observed, including token and permission errors.
  Do not rely on 401/403/404; branch on `error.code`.
- Token errors add `WWW-Authenticate: OAuth "Facebook Platform" "invalid_token" "<message>"`.
- Every Page-token call returns rate-limit usage, as percentages of the limit:
  ```
  x-business-use-case-usage: {"<page_id>":[{"type":"pages","call_count":1,"total_cputime":1,"total_time":1,"estimated_time_to_regain_access":0}]}
  ```
  `estimated_time_to_regain_access` is in minutes. Page-token calls use these business
  use case (BUC) limits; `X-App-Usage` applies to user/app tokens instead.

### How the bot reports them

`FacebookError` text, as it appears in `/logs` `error` (prefixed `public: ` or `private: `)
and in `/posts` / `/posts/find` `detail`:

```
<METHOD> <path> -> <HTTP status>: <the error object as a Python dict>
POST 300000000000003_1/comments -> 400: {'message': '(#100) Story does not exist ...', 'type': 'OAuthException', 'code': 100, 'fbtrace_id': '...'}
GET 100000000000001/posts -> ConnectTimeout: <details>          # network failure, no HTTP status
```

The access token is never part of the text. The bot does **not** branch on codes or retry:
any failure is recorded and that reply is not sent; the other reply (public or private) is
still attempted. Reading the post text for the AI ignores failures.

### By call (verified)

| Call | Case | HTTP | `code` / `error_subcode` | `message` (start) |
|---|---|---|---|---|
| any | Invalid token | 400 | 190 | `Invalid OAuth access token - Cannot parse access token` |
| any | No token | 400 | 2500 | `An active access token must be used to query information about the current user.` |
| any | Unknown edge (`/{page_id}/nope`) | 400 | 2500 | `Unknown path components: /nope` |
| any | Unknown field in `fields=` | 200 | none | No error: the field is ignored |
| any | Unsupported version (`/v1.0/...`) | 200 | none | No error: upgraded to the oldest supported version |
| `GET /{page_id}/posts` | `limit` > 100 | 400 | 100 | `(#100) The 'limit' parameter should not exceed 100` |
| `GET /{page_id}/posts` | App token instead of Page token | 400 | 100 | `(#100) Object does not exist, cannot be loaded due to missing permission or reviewable feature ... requires the 'pages_read_engagement' permission ...` |
| `GET /{page_id}/accounts`-style | Field that does not exist on the node | 400 | 100 | `(#100) Tried accessing nonexisting field (accounts)` |
| `GET /{post_id}` | Bare post id (no `{page_id}_`) | 400 | 12 | `(#12) singular statuses API is deprecated for versions v2.4 and higher` |
| `GET /{page_id}_{post_id}` | Post does not exist | 400 | 10 | `(#10) Object does not exist, cannot be loaded due to missing permission or reviewable feature ...` |
| `GET /{comment_id}` | Comment deleted | 400 | 100 / 33 | `Unsupported get request. Object with ID '...' does not exist ...` (`type: GraphMethodException`) |
| `POST /{comment_id}/comments` | Comment does not exist | 400 | 100 | `(#100) Story does not exist or user does not have permission to interact with it` |
| `POST /{comment_id}/comments` | Empty `message` | 400 | 100 | `(#100) Param message must be a non-empty UTF-8 encoded string` |
| `POST /{page_id}/messages` | Invalid or unknown `comment_id` | 400 | 100 / 1893060 | `Invalid parameter`; `error_user_title: Invalid private reply comment ID`, `is_transient: false` |
| `POST /{page_id}/messages` | No `text` | 400 | 100 / 2018034 | `(#100) Message cannot be empty. A valid attachment or text must be provided.` |

The bot cannot trigger the `limit`, empty-message or bare-id cases itself: it clamps `limit`
to 1–100, never sends empty text, and always adds the Page id.

### Private reply limits (docs)

Meta documents these as rules without naming the error each one returns:

- Only **one** message per comment.
- Within **7 days** of the post or comment being created.
- After that, the conversation continues only if the person answers, within the 24-hour
  messaging window.
- Not to another Facebook Page (comments posted as a Page cannot get a private reply).
- Standard Access apps can only message people who have a role on the app.

Messenger codes that match these situations (docs):

| `code` / `error_subcode` | Meaning |
|---|---|
| 10 / 2018278 | Message sent outside the allowed window |
| 10 / 2534022 | Outside the allowed window; only send while the standard messaging window is open |
| 10 / 2018108 | The person can't receive your messages right now |
| 10 / 1893063 | The Page is temporarily restricted from sending messages |
| 10 / 2018300 | Another app controls the conversation (handover protocol) |
| 100 / 2534025 | The comment is invalid for a private reply |
| 100 / 2018001 | No matching user found |
| 200 / 2018028 | Cannot message people who are not admins, developers or testers until `pages_messaging` is approved and the app is Live |
| 200 / 1545041 | Message not sent: this person isn't available right now |
| 551 / 1545041 | This person isn't available right now |
| 551 | This person isn't receiving messages from you (blocked the Page) |
| 2 | Unexpected error, retry later. Also seen when the person blocked the Page |
| 4 | Application request limit reached |
| 613 / 2534040 | Messenger rate limit exceeded |
| 9000001 | The message was deleted by the user or the business |

### General Graph codes (docs)

| `code` | Meaning | What to do |
|---|---|---|
| 1 | Unknown error, possibly temporary | Retry later; if it persists, check the call exists |
| 2 | Service temporarily unavailable | Retry later |
| 3 | App lacks the capability or permission for this method | Fix app permissions |
| 4 | App rate limit | Back off; check usage headers |
| 10, 200–299 | Permission missing or removed | Grant the permission (see [Permissions](#permissions)) |
| 17 | User rate limit | Back off |
| 32 | Page rate limit (user or app token) | Back off |
| 80001 | Page rate limit (Page token: this bot's case). Message: `(#80001) There have been too many calls to this Page account. Wait a bit and try again.` | Back off until `estimated_time_to_regain_access` |
| 80006 | Messenger rate limit (BUC) | Back off |
| 100 | Invalid parameter or object (see verified rows) | Fix the request; do not retry |
| 102 | Session or token invalid | Get a new token |
| 190 | Token expired, revoked or invalid | Get a new Page token (see the README) |
| 341 | Application limit reached | Retry later |
| 368 | Temporarily blocked for policy violations (e.g. spam-like posting) | Slow down; retry later |
| 506 | Duplicate post | Change the text |
| 613 | Custom rate limit (`613/1996`: inconsistent request behaviour) | Back off |

`190` subcodes (docs): `458` app not installed, `459` account checkpointed, `460` password
changed, `463` token expired, `464` unconfirmed user, `467` invalid token, `492` the user
behind the Page token no longer has a role on the Page. All mean: generate a new Page token.

Retry guide for callers: retry with backoff on network errors, `is_transient: true`, codes
1, 2, 4, 17, 32, 341, 613, 80001, 80006. Never retry 100, 190, 10/200–299 or 551 without
changing something first; a second private reply to the same comment is not allowed anyway.

## Bot endpoints

Parameters, headers, responses and errors for every endpoint the bot serves:
[endpoints.md](endpoints.md).

## Sources

- Webhooks (delivery, retries, signature): <https://developers.facebook.com/docs/graph-api/webhooks/getting-started>
- Messenger webhooks (5-second limit, alerts, unsubscribe after 1 hour): <https://developers.facebook.com/docs/messenger-platform/webhooks>
- Webhooks for Pages: <https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-pages>
- `feed` webhook field reference: <https://developers.facebook.com/docs/graph-api/webhooks/reference/page/#feed>
- Comments: <https://developers.facebook.com/docs/graph-api/reference/object/comments/>
- Private replies: <https://developers.facebook.com/docs/messenger-platform/discovery/private-replies/>
- Error handling and codes: <https://developers.facebook.com/docs/graph-api/guides/error-handling/>
- Messenger error codes: <https://developers.facebook.com/docs/messenger-platform/error-codes>
- Rate limiting and usage headers: <https://developers.facebook.com/docs/graph-api/overview/rate-limiting/>
- Graph API changelog and version dates: <https://developers.facebook.com/docs/graph-api/changelog/versions>
