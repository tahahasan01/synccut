"""Settings from the environment, with a minimal .env loader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines without overriding real env vars.

    Keys are normalised (``Anthropic-api-key`` → ``ANTHROPIC_API_KEY``).
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip().upper().replace("-", "_")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SYNCCUT_DATA_DIR", REPO_ROOT / "data")))
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None)
    anthropic_auth_token: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_AUTH_TOKEN") or None)
    claude_model: str = field(default_factory=lambda: os.environ.get("SYNCCUT_CLAUDE_MODEL", "claude-opus-5-5"))
    whisper_model: str = field(default_factory=lambda: os.environ.get("SYNCCUT_WHISPER_MODEL", "base.en"))
    web_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.environ.get("SYNCCUT_WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        )
    )
    # where the API can reach itself; the stage renderer loads the stage page from here
    api_base: str = field(default_factory=lambda: os.environ.get("SYNCCUT_API_BASE", "http://127.0.0.1:8000").rstrip("/"))
    fps: int = 30
    max_upload_mb: int = 4096


settings = Settings()
