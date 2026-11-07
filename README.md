---
title: fb-auto-reply
sdk: docker
app_port: 7860
---

# fb-auto-reply

[![CI](https://github.com/henryle97/fb-auto-reply/actions/workflows/ci.yml/badge.svg)](https://github.com/henryle97/fb-auto-reply/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Automatically reply to comments on a Facebook Page. Keyword rules give instant, free answers.
Everything else goes to Claude, which answers from your product notes. Every reply is
written in the commenter's own language.

For each new comment, the bot:

1. Skips the Page's own comments, edits, photo/sticker-only comments and `ignore_keywords`.
2. Deduplicates redelivered webhooks (each comment is claimed once in SQLite or Supabase).
3. Picks a reply: the first matching **keyword rule** in `rules.yaml`, otherwise **Claude**
   using `product_info.md`. Claude skips spam and comments that only tag friends.
4. Waits a random 5–20 s, posts a **public reply** under the comment and sends a **private
   reply** to the commenter's Messenger inbox.
5. Records the outcome (`GET /logs`).

## Project layout

```
src/fb_auto_reply/
  main.py        FastAPI app: /webhook plus admin endpoints
  processor.py   Handling of one comment
  rules.py       Keyword matching, templates, language detection
  ai.py          Claude replies
  facebook.py    Graph API client and webhook signature check
  store.py       SQLite or Supabase
  cli.py         `fb-auto-reply check` / `fb-auto-reply ask`
examples/        Starter rules.yaml and product_info.md
tests/
```

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env                                  # fill in the values (see below)
cp examples/rules.example.yaml rules.yaml             # your keyword rules
cp examples/product_info.example.md product_info.md   # what the AI may say
uv run uvicorn fb_auto_reply.main:create_app --factory --port 7860
```

`rules.yaml` and `product_info.md` are gitignored, so your page's content stays out of the
repo. If they are missing, the files in `examples/` are used.

Facebook needs a public HTTPS URL. For local testing, use a tunnel:

```bash
cloudflared tunnel --url http://localhost:7860
```

`DRY_RUN=true` (the default) logs what would be posted without posting it. Set it to `false`
when the replies in `/logs` look right.

## Facebook setup

1. Create an app at <https://developers.facebook.com/apps> (type **Business**) and add the
   **Webhooks** and **Messenger** products. Copy **App settings → Basic → App secret** into
   `FB_APP_SECRET`.
2. Get a non-expiring Page access token.
   - In **Graph API Explorer**, select your app and add the permissions `pages_show_list`,
     `pages_read_engagement`, `pages_manage_engagement`, `pages_manage_metadata`,
     `pages_messaging` and `pages_read_user_content`. Generate a user token.
   - Exchange it for a long-lived user token:
     ```
     GET https://graph.facebook.com/v25.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=USER_TOKEN
     ```
   - Fetch the Page token. A Page token obtained from a long-lived user token does not expire.
     ```
     GET https://graph.facebook.com/v25.0/me/accounts?access_token=LONG_LIVED_USER_TOKEN
     ```
     Put `id` in `FB_PAGE_ID` and `access_token` in `FB_PAGE_ACCESS_TOKEN`.
3. Register the webhook under **Webhooks → Page**.
   - Callback URL: `https://<your-host>/webhook`
   - Verify token: your `FB_VERIFY_TOKEN`
   - Subscribe to the **feed** field.
4. Subscribe the app to the Page:
   ```bash
   curl -X POST "https://graph.facebook.com/v25.0/$FB_PAGE_ID/subscribed_apps?subscribed_fields=feed&access_token=$FB_PAGE_ACCESS_TOKEN"
   ```
5. Check everything (read-only):
   ```bash
   uv run fb-auto-reply check
   ```

> [!IMPORTANT]
> While the app is in **Development** mode, Facebook does not deliver real `feed` webhooks.
> Publish the app (**Live** mode) to receive them.

## Configuration

All settings come from environment variables (or `.env`). See [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`, `FB_APP_SECRET` | — | Facebook credentials |
| `FB_VERIFY_TOKEN` | — | Webhook verify token; also the `X-Admin-Token` for admin endpoints |
| `FB_GRAPH_VERSION` | `v25.0` | Graph API version used for outgoing calls |
| `DRY_RUN` | `true` | Log replies instead of posting them |
| `SEND_PRIVATE_REPLY` | `true` | Also send a Messenger message |
| `REPLY_DELAY_MIN` / `MAX` | `5` / `20` | Random delay before replying, in seconds |
| `AI_ENABLED` | `true` | Use Claude for comments no rule matches |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `CLAUDE_MODEL` / `CLAUDE_EFFORT` | `claude-opus-5-5` / `low` | Model and effort level |
| `RULES_PATH`, `PRODUCT_INFO_PATH` | `rules.yaml`, `product_info.md` | Content files |
| `SQLITE_PATH` | `data.db` | Local storage |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | — | Use Supabase instead of SQLite |

### Rules and languages

Rules match keywords as whole words, ignoring case. A comment typed without accents still
matches accented keywords. Templates are written per language:

```yaml
default_language: en
languages:
  en: {name_fallback: there, words: [the, how, price, free]}
  es: {name_fallback: amigo, chars: "ñ¿¡", words: [el, la, precio, gratis, hola]}

rules:
  - name: pricing
    keywords: [price, how much, precio, cuánto cuesta]
    public_reply:
      en: "It's free to start, {name}! Pricing: https://example.com/pricing"
      es: "¡Puedes empezar gratis, {name}! Precios: https://example.com/pricing"
```

The comment's language is detected from the configured hint words and characters. A comment
in a language the rule has no template for is answered by the AI instead, which always replies
in the commenter's language. See
[`examples/rules.example.yaml`](examples/rules.example.yaml) for every option.

Preview a reply without posting:

```bash
uv run fb-auto-reply ask "how much does it cost?" --name Jane
```

After editing rules on a running server, reload them:

```bash
curl -X POST -H "X-Admin-Token: $FB_VERIFY_TOKEN" https://<your-host>/reload-rules
```

## Endpoints

See [docs/facebook-api.md](docs/facebook-api.md) for every Graph API call, webhook payload
samples, field meanings and API versions.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/` | — | Health check |
| `GET` | `/webhook` | verify token | Facebook webhook verification |
| `POST` | `/webhook` | `X-Hub-Signature-256` | Facebook webhook events |
| `GET` | `/logs?limit=50` | `X-Admin-Token` | Recent comments and replies |
| `POST` | `/reload-rules` | `X-Admin-Token` | Reload `rules.yaml` |
| `GET` | `/debug/payloads` | `X-Admin-Token` | Last 20 raw webhook payloads |

## Deploy to Hugging Face Spaces (free)

1. Create a Space with the **Docker** SDK and push this repo to it.
2. Add the variables from `.env.example` under **Settings → Variables and secrets**. Store the
   tokens and keys as secrets.
3. Provide your content. The Space builds from git, and `rules.yaml` / `product_info.md` are
   gitignored, so by default the examples are used. To ship your own, force-add them
   (`git add -f rules.yaml product_info.md`) **only in a separate clone that pushes to the
   Space and never to a public remote**.
4. Your webhook URL is `https://<user>-<space>.hf.space/webhook`.

Free Spaces sleep when idle and lose their disk on restart. Use
[Supabase](https://supabase.com) (free tier) for durable deduplication: run
[`supabase_schema.sql`](supabase_schema.sql) in the SQL editor, then set `SUPABASE_URL` and
`SUPABASE_SERVICE_KEY` (the service_role key).

## Facebook limits

- A private reply can be sent **once per comment**, within **7 days** of the comment. If it
  fails, the public reply is kept and the error is recorded.
- Fast or identical replies look like spam. The random delay and multiple templates help.
- `from.name` is sometimes missing from webhooks; `{name}` then uses the language's
  `name_fallback`.
- Webhook payloads use the version of the subscribed field. Outgoing calls use
  `FB_GRAPH_VERSION`. The two do not need to match.

## Development

```bash
uv sync
uv run pre-commit install   # ruff, secret scan (gitleaks) and file checks on every commit
uv run pytest
uv run ruff check
uv run ruff format
```

## License

[MIT](LICENSE)
