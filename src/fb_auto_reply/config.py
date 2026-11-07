"""Settings loaded from environment variables (and a local `.env` file, if present)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

EXAMPLE_RULES = Path("examples/rules.example.yaml")
EXAMPLE_PRODUCT_INFO = Path("examples/product_info.example.md")


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal `.env` loader. Variables already set in the environment take precedence."""
    env_file = Path(path)
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _path(name: str, default: str, example: Path) -> str:
    """Use the configured file; fall back to the bundled example when the default is missing."""
    value = _env(name)
    if value:
        return value
    if Path(default).exists() or not example.exists():
        return default
    log.warning("%s not found, using %s", default, example)
    return str(example)


@dataclass(frozen=True)
class Settings:
    # Facebook
    page_id: str = field(default_factory=lambda: _env("FB_PAGE_ID"))
    page_access_token: str = field(default_factory=lambda: _env("FB_PAGE_ACCESS_TOKEN"))
    app_secret: str = field(default_factory=lambda: _env("FB_APP_SECRET"))
    verify_token: str = field(default_factory=lambda: _env("FB_VERIFY_TOKEN"))
    graph_version: str = field(default_factory=lambda: _env("FB_GRAPH_VERSION", "v25.0"))

    # Behaviour
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))
    send_private_reply: bool = field(default_factory=lambda: _bool("SEND_PRIVATE_REPLY", True))
    reply_delay_min: float = field(default_factory=lambda: _float("REPLY_DELAY_MIN", 5))
    reply_delay_max: float = field(default_factory=lambda: _float("REPLY_DELAY_MAX", 20))

    # AI (Claude)
    ai_enabled: bool = field(default_factory=lambda: _bool("AI_ENABLED", True))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-opus-5-5"))
    claude_effort: str = field(default_factory=lambda: _env("CLAUDE_EFFORT", "low"))

    # Storage: Supabase when configured, otherwise SQLite
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_KEY"))
    sqlite_path: str = field(default_factory=lambda: _env("SQLITE_PATH", "data.db"))
    # Optional: append every raw webhook payload to this JSONL file (contains personal data).
    webhook_log_path: str = field(default_factory=lambda: _env("WEBHOOK_LOG_PATH"))

    # Content
    rules_path: str = field(
        default_factory=lambda: _path("RULES_PATH", "rules.yaml", EXAMPLE_RULES)
    )
    product_info_path: str = field(
        default_factory=lambda: _path("PRODUCT_INFO_PATH", "product_info.md", EXAMPLE_PRODUCT_INFO)
    )

    @classmethod
    def from_env(cls, dotenv: str | Path | None = ".env") -> Settings:
        if dotenv:
            load_dotenv(dotenv)
        return cls()
