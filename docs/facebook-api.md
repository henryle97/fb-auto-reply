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
the `access_token` query parameter. Errors come back as HTTP 4xx with a JSON body
`{"error": {"message", "type", "code", "error_subcode", "fbtrace_id"}}`, raised as
`FacebookError`.

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

Response:

```json
{"recipient_id": "...", "message_id": "m_..."}
```

Limits: **one** private reply per comment, within **7 days** of the comment. After that, the
call fails. The bot keeps the public reply and records the error.

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
returns 403.

### Events: `POST /webhook`

Full schema and every captured payload: [webhook-payloads.md](webhook-payloads.md).

Every event is signed with the app secret:

```
X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw request body, key = FB_APP_SECRET>
```

Requests with a missing or invalid signature get 401. Valid ones get 200 immediately, and
replies happen in the background. Facebook retries webhooks that are slow or fail, so the
same comment can arrive more than once; the bot deduplicates by `comment_id`.

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

## Bot endpoints

Parameters, headers, responses and errors for every endpoint the bot serves:
[endpoints.md](endpoints.md).

## Sources

- Webhooks for Pages: <https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-pages>
- `feed` webhook field reference: <https://developers.facebook.com/docs/graph-api/webhooks/reference/page/#feed>
- Comments: <https://developers.facebook.com/docs/graph-api/reference/object/comments/>
- Private replies: <https://developers.facebook.com/docs/messenger-platform/discovery/private-replies/>
- Graph API changelog and version dates: <https://developers.facebook.com/docs/graph-api/changelog/versions>
