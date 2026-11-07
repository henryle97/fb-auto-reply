# Webhook payloads (captured live)

Every payload on this page was **received from Facebook by this bot** on 2026-11-07, with
the Page's `feed` webhook field at version **v27.0**. Nothing is copied from Meta's docs.
Ids, names, messages and URLs are replaced by placeholders, but each payload's structure,
key order, types and the other values are exactly as received.

Placeholder ids are consistent across examples: `900000000000001` is the Page, and the same
number always means the same object.

To capture more, set `WEBHOOK_LOG_PATH=logs/webhooks.jsonl`, trigger events on the Page, then
regenerate the examples below with:

```bash
uv run fb-auto-reply payloads logs/webhooks.jsonl
```

## Envelope

Every POST had one entry with one change.

| Path | Type | Observed values | Notes |
|---|---|---|---|
| `object` | string | `"page"` | |
| `entry[]` | array | 1 element | Code still loops over all entries, in case Facebook batches them |
| `entry[].id` | string | Page id | |
| `entry[].time` | integer | Unix seconds | When Facebook sent the event. Seen 3–6 s after `value.created_time` |
| `entry[].changes[]` | array | 1 element | |
| `entry[].changes[].field` | string | `"feed"` | The subscribed webhook field |
| `entry[].changes[].value` | object | see below | |

Headers: the request carries `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the body with the
app secret>`. Signature checks passed on every captured request.

## `feed` value for comments

| Key | Type | On `add` | On `remove` | Notes |
|---|---|---|---|---|
| `item` | string | `"comment"` | `"comment"` | |
| `verb` | string | `"add"` | `"remove"` | |
| `comment_id` | string | ✓ | ✓ | `<post object id>_<comment object id>` |
| `post_id` | string | ✓ | ✓ | `<page id>_<post object id>` |
| `parent_id` | string | ✓ | ✓ | Top-level comment: equals `post_id`. Reply inside a thread: the parent's `comment_id` |
| `created_time` | integer | ✓ | ✓ | Unix seconds. On `remove` it was 6 s before `entry[].time`; whether it is the creation or deletion time is not confirmed yet |
| `from.id` | string | ✓ | ✓ | Commenter id, or the Page id for the Page's own comments |
| `from.name` | string | ✓ | ✓ | Commenter display name |
| `message` | string | ✓ | ✗ (absent) | Comment text |
| `post` | object | ✓ | ✓ | Snapshot of the post the comment belongs to |
| `post.id` | string | ✓ | ✓ | Same as `post_id` |
| `post.status_type` | string | `"shared_story"` | `"shared_story"` | |
| `post.is_published` | boolean | `true` | `true` | |
| `post.updated_time` | string | ✓ | ✓ | ISO 8601 with `+0000`, e.g. `2026-11-07T04:48:15+0000`. Not Unix seconds, unlike `created_time` |
| `post.permalink_url` | string | ✓ | ✓ | Two formats seen for the same post: `https://www.facebook.com/permalink.php?story_fbid=pfbid...` and `https://www.facebook.com/<id>/posts/<post object id>` |
| `post.promotion_status` | string | `"inactive"` | `"inactive"` | |

Notes from these captures:

- **The Page's own replies come back as webhooks** with `from.id` equal to `entry[].id`. The
  bot ignores them to avoid replying to itself.
- **A reply in a thread** has `parent_id` set to the parent comment's `comment_id`, not the
  post id. The bot's replies are such thread replies.
- **Deleting a comment** sends `verb: "remove"` with the same `comment_id` and no `message`.

## Documented `feed` values (Meta reference, v27.0)

Meta's `feed` reference lists these, without saying which fields go with which item. Only
`item: comment` with `verb: add` / `remove` has been captured here.

- `item`: `album`, `address`, `comment`, `connection`, `coupon`, `event`, `experience`,
  `group`, `group_message`, `interest`, `link`, `mention`, `milestone`, `note`, `page`,
  `picture`, `platform-story`, `photo`, `photo-album`, `post`, `profile`, `question`,
  `rating`, `reaction`, `relationship-status`, `share`, `status`, `story`, `timeline cover`,
  `tag`, `video`
- `verb`: `add`, `block`, `edit`, `edited`, `delete`, `follow`, `hide`, `mute`, `remove`,
  `unblock`, `unhide`, `update`
- `value` fields (union over all items): `action`, `album_id`, `comment_id`, `created_time`,
  `edited_time`, `event_id`, `feedback_target_id`, `from` (`id`, `name`), `is_hidden`,
  `is_published`, `item`, `link`, `message`, `open_graph_story_id`, `parent_id`, `permalink_url`,
  `photo`, `photo_id`, `photo_ids`, `photos`, `post` (object), `post_id`, `published`,
  `reaction_type`, `recipient_id`, `share_id`, `status_type`, `story`, `title`, `updated_time`,
  `verb`, `video`, `video_flag_reason`, `video_id`

Notes from the same reference: no webhook for Ad Posts themselves (comments on them are
sent); Page-like notifications only for Pages under 10K likes. Batches can hold up to 1000
changes, so code must loop over every `entry` and `change` even though each capture here had
one.

## Not captured yet

These events have not reached this bot yet, so their shape is not documented here. They need
a person to act on the Page, or a write by the Page:

- comment edited (`verb: "edited"`?), hidden or unhidden
- a user's reply inside a thread
- a comment with a photo, sticker or GIF only
- reactions and likes on posts and comments
- new, edited or deleted Page posts (status, photo, video, share)
- a comment on an unpublished, scheduled or boosted post

## Examples

### feed: item=comment verb=add

```json
{
  "entry": [
    {
      "id": "900000000000001",
      "time": 1794026898,
      "changes": [
        {
          "value": {
            "from": {
              "id": "900000000000002",
              "name": "<name>"
            },
            "post": {
              "status_type": "shared_story",
              "is_published": true,
              "updated_time": "2026-11-07T04:48:15+0000",
              "permalink_url": "<permalink_url>",
              "promotion_status": "inactive",
              "id": "900000000000001_900000000000003"
            },
            "message": "<message>",
            "post_id": "900000000000001_900000000000003",
            "comment_id": "900000000000003_900000000000005",
            "created_time": 1794026895,
            "item": "comment",
            "parent_id": "900000000000001_900000000000003",
            "verb": "add"
          },
          "field": "feed"
        }
      ]
    }
  ],
  "object": "page"
}
```

### feed: item=comment verb=add (by the Page)

```json
{
  "entry": [
    {
      "id": "900000000000001",
      "time": 1794027981,
      "changes": [
        {
          "value": {
            "from": {
              "id": "900000000000001",
              "name": "<name>"
            },
            "post": {
              "status_type": "shared_story",
              "is_published": true,
              "updated_time": "2026-11-07T05:06:18+0000",
              "permalink_url": "<permalink_url>",
              "promotion_status": "inactive",
              "id": "900000000000001_900000000000003"
            },
            "message": "<message>",
            "post_id": "900000000000001_900000000000003",
            "comment_id": "900000000000003_900000000000006",
            "created_time": 1794027978,
            "item": "comment",
            "parent_id": "900000000000003_900000000000007",
            "verb": "add"
          },
          "field": "feed"
        }
      ]
    }
  ],
  "object": "page"
}
```

### feed: item=comment verb=remove

```json
{
  "entry": [
    {
      "id": "900000000000001",
      "time": 1794026897,
      "changes": [
        {
          "value": {
            "from": {
              "id": "900000000000002",
              "name": "<name>"
            },
            "post": {
              "status_type": "shared_story",
              "is_published": true,
              "updated_time": "2026-09-04T03:07:23+0000",
              "permalink_url": "<permalink_url>",
              "promotion_status": "inactive",
              "id": "900000000000001_900000000000003"
            },
            "post_id": "900000000000001_900000000000003",
            "comment_id": "900000000000003_900000000000004",
            "created_time": 1794026891,
            "item": "comment",
            "parent_id": "900000000000001_900000000000003",
            "verb": "remove"
          },
          "field": "feed"
        }
      ]
    }
  ],
  "object": "page"
}
```
