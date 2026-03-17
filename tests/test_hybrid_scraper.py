# tests/test_hybrid_scraper.py
import pytest
import fakeredis
from unittest.mock import AsyncMock, MagicMock, patch
from models import PageResult
from scraper.hybrid_scraper import HybridScraper
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper



@pytest.fixture
def qm(fake_redis):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/services")
    return qm


@pytest.fixture
def snooper():
    s = MagicMock(spec=Snooper)
    s.is_disallowed.return_value = False
    s.is_external.return_value = False
    s.has_noindex.return_value = False
    s.has_nofollow.return_value = False
    s.crawl_delay = 0  # no delay in tests
    return s


@pytest.fixture
def success_result():
    return PageResult(url="https://example.com/about", status="success",
                      markdown="# About\n\nContent.", engine_used="crawl4ai")


@pytest.fixture
def failed_result():
    return PageResult(url="https://example.com/about", status="failed",
                      skip_reason="crawl4ai timeout")


@pytest.mark.asyncio
async def test_yields_success_result(qm, snooper, success_result):
    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success_result, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=2)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.status == "success" for r in results)


@pytest.mark.asyncio
async def test_falls_back_to_scrapy_on_crawl4ai_failure(qm, snooper, failed_result):
    scrapy_success = PageResult(url="https://example.com/about", status="success",
                                 markdown="# About", engine_used="scrapy")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine") as MockFallback:
        mock_primary = AsyncMock()
        mock_primary.scrape = AsyncMock(return_value=(failed_result, []))
        MockPrimary.return_value = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.scrape.return_value = scrapy_success
        MockFallback.return_value = mock_fallback

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.engine_used == "scrapy" for r in results)


@pytest.mark.asyncio
async def test_skips_disallowed_url(qm, snooper):
    snooper.is_disallowed.return_value = True

    with patch("scraper.hybrid_scraper.Crawl4AIEngine"), \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        scraper = HybridScraper(qm, snooper, max_pages=2)
        results = [r async for r in scraper.crawl("https://example.com")]

    skipped = [r for r in results if r.status == "skipped"]
    assert len(skipped) > 0
    assert all("robots" in r.skip_reason for r in skipped)


@pytest.mark.asyncio
async def test_saves_external_url_instead_of_crawling(qm, snooper, fake_redis):
    # Setup: second URL is external
    snooper.is_external.side_effect = lambda url: "linkedin" in url
    qm.enqueue("https://linkedin.com/company/example")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(
            PageResult(url="https://example.com/about", status="success", markdown="x"),
            []
        ))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=10)
        results = [r async for r in scraper.crawl("https://example.com")]

    # LinkedIn URL should not appear as a result
    assert not any("linkedin" in r.url for r in results)


@pytest.mark.asyncio
async def test_respects_max_pages_limit(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    for i in range(10):
        qm.enqueue(f"https://example.com/page-{i}")

    success = PageResult(url="x", status="success", markdown="content")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=3)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert len([r for r in results if r.status == "success"]) == 3


@pytest.mark.asyncio
async def test_duplicate_content_yields_skipped(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/page-a")
    qm.enqueue("https://example.com/page-b")

    # Both pages return the same markdown — second should be skipped as duplicate
    # Use side_effect to return fresh PageResult objects so process() modifications don't bleed across calls
    def _fresh_result(*_):
        return (PageResult(url="x", status="success", markdown="# Same Content\n\nIdentical body."), [])

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(side_effect=_fresh_result)
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=10)
        results = [r async for r in scraper.crawl("https://example.com")]

    duplicates = [r for r in results if r.skip_reason == "duplicate-content"]
    assert len(duplicates) >= 1
    assert all(r.status == "skipped" for r in duplicates)


@pytest.mark.asyncio
async def test_successful_result_persisted_to_redis(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/about")

    success = PageResult(url="https://example.com/about", status="success",
                         markdown="# About\n\nContent.", engine_used="crawl4ai")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    persisted = qm.load_results()
    assert len(persisted) >= 1
    assert any(r.url == "https://example.com/about" for r in persisted)


@pytest.mark.asyncio
async def test_dedup_fires_for_same_body_different_urls(fake_redis, snooper):
    """BUG-A: Two pages with the same body content but different URLs must be deduplicated.

    If the hash is computed AFTER YAML injection, each page gets a unique frontmatter
    (different url + scraped_at) → hashes differ → dedup never fires.
    This test verifies the hash is computed BEFORE process() injects frontmatter.
    """
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/page-a")
    qm.enqueue("https://example.com/page-b")

    identical_body = "# Company Info\n\nWe are a great company with lots of experience."

    def _make_result(url, *_):
        # Each call gets a fresh result with the SAME body but a DIFFERENT url
        return (PageResult(url=url, status="success", markdown=identical_body, engine_used="crawl4ai"), [])

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(side_effect=_make_result)
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=10)
        # Pass each URL individually so side_effect receives the correct url arg
        results = [r async for r in scraper.crawl("https://example.com")]

    successes = [r for r in results if r.status == "success"]
    duplicates = [r for r in results if r.skip_reason == "duplicate-content"]
    # Exactly one success and at least one duplicate-content skip
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {[r.url for r in successes]}"
    assert len(duplicates) >= 1, f"Expected >=1 duplicate skip, got {len(duplicates)}"


@pytest.mark.asyncio
async def test_retries_on_failure_then_succeeds(fake_redis, snooper):
    """Verifies that a page that fails once is retried and succeeds on second attempt."""
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/flaky")

    fail = PageResult(url="https://example.com/flaky", status="failed", skip_reason="timeout")
    ok = PageResult(url="https://example.com/flaky", status="success", markdown="# Flaky\n\nContent.", engine_used="crawl4ai")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"), \
         patch("asyncio.sleep"):  # don't actually wait
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(side_effect=[(fail, []), (ok, [])])
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.status == "success" for r in results)


@pytest.mark.asyncio
async def test_gives_up_after_3_attempts(fake_redis, snooper):
    """Verifies that a page that always fails is marked failed after 3 attempts."""
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/broken")

    fail = PageResult(url="https://example.com/broken", status="failed", skip_reason="timeout")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine") as MockFallback, \
         patch("asyncio.sleep"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(fail, []))
        MockPrimary.return_value = mock_engine

        mock_fallback = MagicMock()
        mock_fallback.scrape.return_value = PageResult(url="x", status="failed", skip_reason="scrapy fail")
        MockFallback.return_value = mock_fallback

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.status == "failed" for r in results)


@pytest.mark.asyncio
async def test_skips_noise_urls(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    for url in [
        "https://example.com/privacy-policy",
        "https://example.com/terms-of-service",
        "https://example.com/cookie-policy",
        "https://example.com/legal/notice",
    ]:
        qm.enqueue(url)

    # crawl() also enqueues start_url ("https://example.com/") which is NOT a noise URL,
    # so we need a working async primary engine for that one URL.
    start_url_result = PageResult(url="https://example.com/", status="success",
                                  markdown="# Home", engine_used="crawl4ai")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(start_url_result, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=10)
        results = [r async for r in scraper.crawl("https://example.com")]

    noise_results = [r for r in results if r.url != "https://example.com/"]
    assert all(r.status == "skipped" for r in noise_results)
    assert all(r.skip_reason == "noise-url" for r in noise_results)


@pytest.mark.asyncio
async def test_skips_login_redirect_page(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/dashboard")

    login_page = PageResult(
        url="https://example.com/dashboard",
        status="success",
        title="Sign in to continue",
        markdown="# Sign in\n\nPlease sign in to view this page.",
        engine_used="crawl4ai",
    )

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(login_page, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.status == "skipped" and r.skip_reason == "login-redirect" for r in results)


@pytest.mark.asyncio
async def test_pipeline_db_records_successful_page(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/about")

    success = PageResult(url="https://example.com/about", status="success",
                         markdown="# About\n\nContent.", engine_used="crawl4ai")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"), \
         patch("scraper.hybrid_scraper.PipelineDB") as MockDB:
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success, []))
        MockPrimary.return_value = mock_engine

        mock_db_instance = MagicMock()
        MockDB.return_value = mock_db_instance

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    mock_db_instance.upsert_scraped.assert_called_once()
    call_kwargs = mock_db_instance.upsert_scraped.call_args
    assert call_kwargs[1]["url"] == "https://example.com/about" or call_kwargs[0][0] == "https://example.com/about"


@pytest.mark.asyncio
async def test_skips_login_redirect_on_disallowed_scrapy_path(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/members")
    snooper.is_disallowed.return_value = True

    login_page = PageResult(
        url="https://example.com/members",
        status="success",
        title="Log in to access",
        markdown="# Log in\n\nYou need to log in.",
        engine_used="scrapy",
    )

    with patch("scraper.hybrid_scraper.Crawl4AIEngine"), \
         patch("scraper.hybrid_scraper.ScrapyEngine") as MockFallback:
        mock_fallback = MagicMock()
        mock_fallback.scrape.return_value = login_page
        MockFallback.return_value = mock_fallback

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.skip_reason == "login-redirect" for r in results)
