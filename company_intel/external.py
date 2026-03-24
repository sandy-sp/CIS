from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from company_intel.classifier import PageClassifier
from company_intel.cleaner import CorpusCleaner
from company_intel.models import PageRecord
from company_intel.review import external_review_status
from scraper.http_utils import get_with_ssl_fallback
from scraper.static_engine import StaticEngine


_ALLOWED_DOMAINS = (
    "linkedin.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "wikipedia.org",
    "github.com",
    "crunchbase.com",
)

_SEARCH_ENGINE_DOMAINS = (
    "duckduckgo.com",
    "google.com",
    "bing.com",
    "search.yahoo.com",
)

_SEARCH_QUERY_HINTS = (
    ("company_profile", 'site:linkedin.com/company "{company_name}"'),
    ("encyclopedia", 'site:wikipedia.org "{company_name}"'),
    ("video", 'site:youtube.com "{company_name}"'),
    ("code", 'site:github.com "{company_name}"'),
    ("profile", '"{company_name}" company profile'),
    ("news", '"{company_name}" latest news'),
)

_DOMAIN_SCORES = {
    "linkedin.com": 92,
    "crunchbase.com": 88,
    "wikipedia.org": 86,
    "github.com": 80,
    "youtube.com": 76,
    "x.com": 70,
    "twitter.com": 70,
    "facebook.com": 66,
    "instagram.com": 64,
}

_QUERY_KIND_BONUS = {
    "company_profile": 8,
    "encyclopedia": 6,
    "code": 5,
    "video": 4,
    "profile": 3,
    "news": 2,
}


@dataclass
class SearchResult:
    query: str
    url: str
    title: str = ""
    snippet: str = ""
    provider: str = ""
    rank: int = 0
    query_kind: str = ""


@dataclass
class ExternalCollectionReport:
    records: list[PageRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    search_results: list[SearchResult] = field(default_factory=list)


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        ...


class DuckDuckGoSearchProvider:
    SEARCH_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = "Business-Scraper/1.0"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        try:
            response = get_with_ssl_fallback(
                self.SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": self.USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"search error: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for rank, node in enumerate(soup.select(".result"), start=1):
            anchor = node.select_one(".result__a") or node.find("a")
            if not anchor:
                continue
            url = self._extract_result_url(anchor.get("href", ""))
            if not url:
                continue
            title = anchor.get_text(" ", strip=True)
            snippet_node = node.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append(
                SearchResult(
                    query=query,
                    url=url,
                    title=title,
                    snippet=snippet,
                    provider="duckduckgo",
                    rank=rank,
                )
            )
            if len(results) >= limit:
                break
        return results

    def _extract_result_url(self, href: str) -> str:
        if not href:
            return ""
        parsed = urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target)
        return href


def _domain_to_company_name(domain: str) -> str:
    root = domain.split(".")[0]
    root = re.sub(r"[-_]+", " ", root)
    root = re.sub(r"\s+", " ", root).strip()
    return root.title() if root else domain


def _title_candidates(title: str) -> list[str]:
    if not title:
        return []
    parts = re.split(r"\s*[\|\-:]\s*", title)
    candidates = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        words = part.split()
        if 1 <= len(words) <= 6:
            candidates.append(part)
    return candidates


def infer_company_names(domain: str, records: list[PageRecord]) -> list[str]:
    candidates: list[str] = []
    priority_records = sorted(
        records,
        key=lambda record: (
            0 if record.page_category == "homepage" else 1,
            0 if record.page_category == "company" else 1,
            len(record.path or ""),
        ),
    )
    for record in priority_records[:5]:
        candidates.extend(_title_candidates(record.title))

    candidates.append(_domain_to_company_name(domain))

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip(" -|:")
        key = normalized.lower()
        if not normalized or len(normalized) < 3 or key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered[:3]


def rank_external_source(url: str, discovered_via: str, metadata: dict | None = None) -> tuple[int, str]:
    metadata = metadata or {}
    parsed = urlparse(url)
    domain = parsed.netloc.lstrip("www.").lower()
    base_score = _DOMAIN_SCORES.get(domain, 58)

    if discovered_via == "site-external-link":
        score = min(base_score + 6, 100)
        reason = f"Found as a public outbound link on the company site ({domain})."
        return score, reason

    query_kind = metadata.get("search_kind", "")
    rank = int(metadata.get("search_rank", 0) or 0)
    score = base_score + _QUERY_KIND_BONUS.get(query_kind, 1)
    if rank > 0:
        score -= min((rank - 1) * 4, 16)
    reason_parts = [f"Search-discovered on {metadata.get('source_domain', domain)}"]
    if query_kind:
        reason_parts.append(f"query type: {query_kind}")
    if rank:
        reason_parts.append(f"rank {rank}")
    return max(1, min(score, 100)), " | ".join(reason_parts)


class ExternalCollector:
    def __init__(self, limit_per_domain: int = 5,
                 search_provider: SearchProvider | None = None,
                 engine: StaticEngine | None = None,
                 search_limit_per_query: int = 3,
                 max_search_results: int = 10):
        self.limit_per_domain = limit_per_domain
        self.search_limit_per_query = search_limit_per_query
        self.max_search_results = max_search_results
        self._engine = engine or StaticEngine()
        self._classifier = PageClassifier()
        self._cleaner = CorpusCleaner()
        self._search_provider = search_provider or DuckDuckGoSearchProvider()

    def collect(self, links: dict[str, list[str]], domain: str,
                internal_records: list[PageRecord] | None = None) -> ExternalCollectionReport:
        records: list[PageRecord] = []
        warnings: list[str] = []
        seen_urls: set[str] = set()
        internal_records = internal_records or []

        for record in self._collect_site_links(links, seen_urls=seen_urls):
            records.append(record)

        company_names = infer_company_names(domain, internal_records)
        search_results: list[SearchResult] = []
        if company_names:
            try:
                search_results = self._discover_search_results(
                    domain=domain,
                    company_names=company_names,
                    seen_urls=seen_urls,
                )
            except Exception as exc:
                warnings.append(str(exc))

        for result in search_results:
            seen_urls.add(result.url)
            records.append(self._build_record(result.url, discovered_via="search", metadata={
                "source_domain": urlparse(result.url).netloc.lstrip("www."),
                "search_provider": result.provider,
                "search_query": result.query,
                "search_kind": result.query_kind,
                "search_rank": result.rank,
                "search_title": result.title,
                "search_snippet": result.snippet,
            }))
        return ExternalCollectionReport(records=records, warnings=warnings, search_results=search_results)

    def _collect_site_links(self, links: dict[str, list[str]], seen_urls: set[str]) -> list[PageRecord]:
        records: list[PageRecord] = []
        for domain, urls in sorted(links.items()):
            if not self._is_allowed(domain):
                continue
            for url in list(dict.fromkeys(urls))[: self.limit_per_domain]:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                record = self._build_record(
                    url,
                    discovered_via="site-external-link",
                    metadata={"source_domain": domain},
                )
                records.append(record)
        return records

    def _discover_search_results(self, domain: str, company_names: list[str],
                                 seen_urls: set[str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for company_name in company_names:
            for query_kind, template in _SEARCH_QUERY_HINTS:
                query = template.format(company_name=company_name)
                for result in self._search_provider.search(query, limit=self.search_limit_per_query):
                    if len(results) >= self.max_search_results:
                        return results
                    result = replace(result, query_kind=query_kind or result.query_kind)
                    if not self._is_search_result_allowed(result, domain=domain, seen_urls=seen_urls, company_names=company_names):
                        continue
                    results.append(result)
                    seen_urls.add(result.url)
        return results

    def _is_search_result_allowed(self, result: SearchResult, domain: str,
                                  seen_urls: set[str], company_names: list[str]) -> bool:
        parsed = urlparse(result.url)
        result_domain = parsed.netloc.lstrip("www.").lower()
        if not result_domain or result.url in seen_urls:
            return False
        if result_domain == domain or result_domain.endswith(f".{domain}"):
            return False
        if any(result_domain == blocked or result_domain.endswith(f".{blocked}") for blocked in _SEARCH_ENGINE_DOMAINS):
            return False

        haystack = " ".join([result.title, result.snippet, result.url]).lower()
        if any(name.lower() in haystack for name in company_names if len(name) >= 4):
            return True

        query_lower = result.query.lower()
        if "site:" in query_lower:
            return True
        return False

    def _build_record(self, url: str, discovered_via: str, metadata: dict | None = None) -> PageRecord:
        result = self._engine.scrape(url)
        parsed = urlparse(url)
        payload = dict(metadata or {})
        review_score, review_reason = rank_external_source(url, discovered_via, payload)
        payload["review_score"] = review_score
        payload["review_reason"] = review_reason
        payload.setdefault("review_status", "approved" if discovered_via == "site-external-link" else "pending")
        payload.setdefault("review_source", "auto")
        record = PageRecord(
            url=url,
            normalized_url=url,
            domain=parsed.netloc.lstrip("www."),
            path=parsed.path or "/",
            source_type="external",
            discovered_via=discovered_via,
            title=result.title,
            description=result.description,
            headings=[],
            language=result.language,
            raw_html=result.raw_html,
            raw_text=result.markdown,
            markdown=result.markdown,
            status=result.status,
            status_code=200 if result.status == "success" else 0,
            engine_selected="static",
            engine_used=result.engine_used,
            metadata=payload,
        )
        payload["review_status"] = external_review_status(record)
        record = self._cleaner.clean_record(record)
        category, subtype, confidence = self._classifier.classify(record)
        record.page_category = category if category != "other" else "external-profile"
        record.page_subtype = subtype
        record.category_confidence = confidence
        return record

    def _is_allowed(self, domain: str) -> bool:
        return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in _ALLOWED_DOMAINS)
