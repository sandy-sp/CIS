from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class PageResult:
    url: str
    canonical_url: str = ""
    title: str = ""
    description: str = ""
    language: str = ""
    headings: list = field(default_factory=list)
    raw_html: str = ""
    markdown: str = ""
    page_type: str = "other"
    word_count: int = 0
    scraped_at: datetime = field(default_factory=_utcnow)
    engine_used: str = ""
    status: str = "failed"
    skip_reason: str = ""
