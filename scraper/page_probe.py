from __future__ import annotations

from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from scraper.http_utils import get_with_ssl_fallback


_JS_MARKERS = (
    "__next_data__",
    "data-reactroot",
    "id=\"__next\"",
    "id=\"root\"",
    "webpack",
    "hydration",
    "astro-island",
    "window.__",
)


@dataclass
class ProbeResult:
    primary_engine: str
    reason: str
    status_code: int = 0
    text_ratio: float = 0.0
    script_count: int = 0
    markers: list[str] = field(default_factory=list)


class EngineRouter:
    USER_AGENT = "Business-Scraper/1.0"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def probe(self, url: str) -> ProbeResult:
        try:
            resp = get_with_ssl_fallback(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.timeout,
            )
            html = resp.text or ""
        except requests.RequestException:
            return ProbeResult(primary_engine="crawl4ai", reason="probe-failed")

        lower_html = html.lower()
        markers = [marker for marker in _JS_MARKERS if marker in lower_html]
        script_count = lower_html.count("<script")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        text_ratio = len(text) / max(len(html), 1)

        if markers:
            return ProbeResult(
                primary_engine="crawl4ai",
                reason="js-markers",
                status_code=resp.status_code,
                text_ratio=text_ratio,
                script_count=script_count,
                markers=markers,
            )

        if script_count >= 10 and text_ratio < 0.12:
            return ProbeResult(
                primary_engine="crawl4ai",
                reason="script-heavy",
                status_code=resp.status_code,
                text_ratio=text_ratio,
                script_count=script_count,
            )

        if len(text) < 120 and len(html) > 5000:
            return ProbeResult(
                primary_engine="crawl4ai",
                reason="thin-static-text",
                status_code=resp.status_code,
                text_ratio=text_ratio,
                script_count=script_count,
            )

        return ProbeResult(
            primary_engine="scrapling",
            reason="static-friendly",
            status_code=resp.status_code,
            text_ratio=text_ratio,
            script_count=script_count,
        )
