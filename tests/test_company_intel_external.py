from models import PageResult

from company_intel.external import ExternalCollector, SearchResult, rank_external_source
from company_intel.models import PageRecord


class FakeEngine:
    def scrape(self, url: str) -> PageResult:
        return PageResult(
            url=url,
            title="Example External Source",
            description="External profile for Example Biotech.",
            language="en",
            raw_html="<html><body><h1>Example External Source</h1><p>Example Biotech company profile.</p></body></html>",
            markdown="# Example External Source\n\nExample Biotech company profile.",
            engine_used="static",
            status="success",
        )


class FakeSearchProvider:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query: str, limit: int = 5):
        self.queries.append(query)
        return self.results.get(query, [])[:limit]


def test_external_collector_combines_site_links_and_search_results():
    search_results = {
        'site:linkedin.com/company "Example Biotech"': [
            SearchResult(
                query='site:linkedin.com/company "Example Biotech"',
                url="https://www.linkedin.com/company/example-biotech",
                title="Example Biotech | LinkedIn",
                snippet="Example Biotech company page.",
                provider="fake",
                rank=1,
            )
        ],
        '"Example Biotech" latest news': [
            SearchResult(
                query='"Example Biotech" latest news',
                url="https://news.example.org/example-biotech-funding",
                title="Example Biotech raises funding",
                snippet="Example Biotech announced new funding.",
                provider="fake",
                rank=1,
            )
        ],
    }
    collector = ExternalCollector(
        engine=FakeEngine(),
        search_provider=FakeSearchProvider(search_results),
        search_limit_per_query=2,
        max_search_results=5,
    )
    internal_records = [
        PageRecord(
            url="https://example.com/",
            normalized_url="https://example.com/",
            domain="example.com",
            path="/",
            title="Example Biotech | Example",
            page_category="homepage",
            status="success",
            markdown="# Example",
            clean_text="Example",
            word_count=1,
        )
    ]

    report = collector.collect(
        {"youtube.com": ["https://www.youtube.com/@examplebiotech"]},
        domain="example.com",
        internal_records=internal_records,
    )

    urls = {record.url for record in report.records}
    assert "https://www.youtube.com/@examplebiotech" in urls
    assert "https://www.linkedin.com/company/example-biotech" in urls
    assert "https://news.example.org/example-biotech-funding" in urls
    search_record = next(record for record in report.records if record.discovered_via == "search")
    assert search_record.metadata["search_provider"] == "fake"
    assert search_record.metadata["review_score"] >= 50
    assert "Search-discovered" in search_record.metadata["review_reason"]
    assert search_record.source_type == "external"


def test_external_collector_filters_first_party_and_search_engine_results():
    provider = FakeSearchProvider({
        '"Example" company profile': [
            SearchResult(
                query='"Example" company profile',
                url="https://example.com/about",
                title="Example",
                snippet="Example company site",
                provider="fake",
                rank=1,
            ),
            SearchResult(
                query='"Example" company profile',
                url="https://www.google.com/search?q=example",
                title="Google",
                snippet="Search results",
                provider="fake",
                rank=2,
            ),
            SearchResult(
                query='"Example" company profile',
                url="https://profiles.example.net/company/example",
                title="Example company profile",
                snippet="Independent profile for Example.",
                provider="fake",
                rank=3,
            ),
        ]
    })
    collector = ExternalCollector(
        engine=FakeEngine(),
        search_provider=provider,
        search_limit_per_query=5,
        max_search_results=5,
    )

    report = collector.collect({}, domain="example.com", internal_records=[])

    urls = [record.url for record in report.records]
    assert "https://profiles.example.net/company/example" in urls
    assert "https://example.com/about" not in urls
    assert "https://www.google.com/search?q=example" not in urls


def test_external_collector_returns_warning_when_search_provider_fails():
    class FailingSearchProvider:
        def search(self, query: str, limit: int = 5):
            raise RuntimeError("search provider unavailable")

    collector = ExternalCollector(
        engine=FakeEngine(),
        search_provider=FailingSearchProvider(),
    )
    internal_records = [
        PageRecord(
            url="https://example.com/",
            normalized_url="https://example.com/",
            domain="example.com",
            path="/",
            title="Example Biotech | Example",
            page_category="homepage",
            status="success",
            markdown="# Example",
            clean_text="Example",
            word_count=1,
        )
    ]

    report = collector.collect({}, domain="example.com", internal_records=internal_records)

    assert report.records == []
    assert any("search provider unavailable" in warning for warning in report.warnings)


def test_rank_external_source_prefers_site_linked_profiles():
    site_score, site_reason = rank_external_source(
        "https://www.linkedin.com/company/example-biotech",
        "site-external-link",
        {"source_domain": "linkedin.com"},
    )
    search_score, search_reason = rank_external_source(
        "https://news.example.org/example-biotech-funding",
        "search",
        {"source_domain": "news.example.org", "search_kind": "news", "search_rank": 3},
    )

    assert site_score > search_score
    assert "outbound link" in site_reason.lower()
    assert "rank 3" in search_reason
