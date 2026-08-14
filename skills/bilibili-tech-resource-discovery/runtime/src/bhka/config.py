from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    project_root: Path
    openai_api_key: str | None
    openai_model: str
    deepseek_api_key: str | None
    deepseek_model: str
    deepseek_base_url: str
    cookies_file: Path | None
    cookies_from_browser: str | None
    bilibili_user_agent: str | None
    timeout_seconds: int
    retries: int
    rate_limit_seconds: float
    firecrawl_api_key: str | None = None
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_search_limit: int = 8
    firecrawl_timeout_seconds: int = 60
    cache_ttl_hours: int = 168

    @classmethod
    def load(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path.cwd()).resolve()
        load_dotenv(root / ".env")
        cookie_value = os.getenv("BILIBILI_COOKIES_FILE", "").strip()
        return cls(
            project_root=root,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            cookies_file=Path(cookie_value).expanduser() if cookie_value else None,
            cookies_from_browser=os.getenv("BILIBILI_COOKIES_FROM_BROWSER") or None,
            bilibili_user_agent=os.getenv("BILIBILI_USER_AGENT") or None,
            timeout_seconds=int(os.getenv("BILIBILI_TIMEOUT_SECONDS", "20")),
            retries=int(os.getenv("BILIBILI_RETRIES", "1")),
            rate_limit_seconds=float(os.getenv("BILIBILI_RATE_LIMIT_SECONDS", "2.5")),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY") or None,
            firecrawl_base_url=os.getenv(
                "FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"
            ).rstrip("/"),
            firecrawl_search_limit=max(
                1, min(10, int(os.getenv("FIRECRAWL_SEARCH_LIMIT", "8")))
            ),
            firecrawl_timeout_seconds=max(
                10, min(120, int(os.getenv("FIRECRAWL_TIMEOUT_SECONDS", "60")))
            ),
            cache_ttl_hours=max(
                1, min(720, int(os.getenv("BHKA_CACHE_TTL_HOURS", "168")))
            ),
        )
