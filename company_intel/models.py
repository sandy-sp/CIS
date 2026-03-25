from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields as dataclass_fields
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _filter_dataclass_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in dataclass_fields(cls)}
    return {key: value for key, value in data.items() if key in allowed}


@dataclass
class CrawlSettings:
    start_url: str
    max_pages: int = 500
    rate_limit: float = 1.0
    follow_external_sources: bool = False
    ignore_robots_exclusions: bool = True
    enable_structured_export: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrawlSettings":
        return cls(**_filter_dataclass_kwargs(cls, dict(data)))


@dataclass
class CrawlJob:
    job_id: str
    domain: str
    settings: CrawlSettings
    status: str = "queued"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages_total: int = 0
    pages_scraped: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    pages_blocked: int = 0
    total_words: int = 0
    llm_txt_found: bool = False
    robots_txt_found: bool = False
    seed_count: int = 0
    seed_source: str = "discovery"
    output_dir: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    finished_at: str = ""

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["settings"] = self.settings.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrawlJob":
        payload = _filter_dataclass_kwargs(cls, dict(data))
        payload["settings"] = CrawlSettings.from_dict(dict(data.get("settings") or {}))
        return cls(**payload)


@dataclass
class PageRecord:
    url: str
    normalized_url: str
    domain: str
    path: str
    source_type: str = "internal"
    parent_url: str = ""
    discovered_via: str = "page-link"
    title: str = ""
    description: str = ""
    headings: list[dict] = field(default_factory=list)
    language: str = ""
    raw_html: str = ""
    raw_text: str = ""
    clean_text: str = ""
    markdown: str = ""
    page_category: str = "other"
    page_subtype: str = ""
    category_confidence: float = 0.0
    status: str = "success"
    status_code: int = 0
    engine_selected: str = ""
    engine_used: str = ""
    fetch_attempts: int = 1
    robots_disallowed: bool = False
    llm_disallowed: bool = False
    outbound_links: list[str] = field(default_factory=list)
    content_hash: str = ""
    template_hash: str = ""
    boilerplate_blocks_removed: list[str] = field(default_factory=list)
    is_noise: bool = False
    is_duplicate: bool = False
    canonical_page_id: str = ""
    source_file: str = ""
    word_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageRecord":
        return cls(**data)


@dataclass
class ExtractedEntity:
    entity_type: str
    normalized_key: str
    display_name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    source_urls: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
