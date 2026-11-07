# Security

Please report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab)
rather than in a public issue.

When running this project:

- Keep `.env` out of version control. It holds a Page access token, the app secret and an
  Anthropic API key. Use your host's secret store in production.
- The webhook rejects any request without a valid `X-Hub-Signature-256`, so `FB_APP_SECRET`
  must be set.
- `/logs` and `/debug/payloads` return commenters' names and messages. They require the
  `X-Admin-Token` header; use a long random `FB_VERIFY_TOKEN`.
- Rotate the Page token and API key if they are ever exposed.
