# Business Scraper Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized Streamlit app that crawls a company website and outputs RAG-ready Markdown files with rich YAML frontmatter.

**Architecture:** Crawl4AI is the primary engine (Playwright-backed, LLM-optimised). Scrapy runs as a subprocess fallback when Crawl4AI fails. Redis manages the crawl queue, deduplication, and resumable state. Streamlit's UI runs the crawl in a background thread and polls for results via `st.rerun()`.

**Tech Stack:** Python 3.11, Streamlit, Crawl4AI ≥0.3.5, Scrapy + scrapy-playwright, Playwright/Chromium, Redis 7, html2text, BeautifulSoup4, PyYAML, fakeredis (tests), pytest + pytest-asyncio (tests).

**Spec:** `docs/superpowers/specs/2026-03-17-business-scraper-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `models.py` | `PageResult` dataclass — shared contract between all engines |
| `scraper/__init__.py` | Empty package marker |
| `scraper/snooper.py` | `llm.txt` / `robots.txt` / `noindex` / external URL detection |
| `scraper/queue_manager.py` | Redis-backed crawl queue, URL dedup, content hash dedup, rate-limit delay |
| `scraper/crawl4ai_engine.py` | Primary async scraper using `AsyncWebCrawler` |
| `scraper/scrapy_worker.py` | Standalone Scrapy subprocess script — takes URL arg, prints JSON result to stdout |
| `scraper/scrapy_engine.py` | Spawns `scrapy_worker.py` as subprocess, captures JSON, returns `PageResult` |
| `scraper/page_processor.py` | Injects YAML frontmatter, detects `page_type`, extracts headings, calculates word count |
| `scraper/hybrid_scraper.py` | Async generator orchestrating Crawl4AI → Scrapy fallback per URL |
| `scraper/exporter.py` | Writes `.zip` with `individual_pages/`, `master_site.md`, `external_links.md`, `crawl_report.md` |
| `app.py` | Streamlit UI — input, start/cancel, live feed, stats, download button |
| `tests/conftest.py` | Shared pytest fixtures (fakeredis, sample HTML, sample PageResult) |
| `tests/test_models.py` | PageResult dataclass field/default tests |
| `tests/test_snooper.py` | llm.txt, robots.txt, noindex, external URL detection |
| `tests/test_queue_manager.py` | Enqueue/dequeue, dedup, normalize, visited tracking |
| `tests/test_page_processor.py` | page_type detection, heading extraction, frontmatter injection, word count |
| `tests/test_crawl4ai_engine.py` | Mocked AsyncWebCrawler, success/failure/empty paths |
| `tests/test_scrapy_engine.py` | Mocked subprocess output, JSON parsing, timeout |
| `tests/test_hybrid_scraper.py` | Generator yields, Crawl4AI→Scrapy fallback, skip logic |
| `tests/test_exporter.py` | Zip structure, file naming, master_site ordering, external_links grouping |
| `requirements.txt` | Production dependencies |
| `requirements-dev.txt` | Test/dev dependencies |
| `Dockerfile` | Python 3.11-slim + Chromium + Playwright |
| `docker-compose.yml` | `app` + `redis` services with volumes |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `scraper/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini`

- [ ] **Step 1: Create `requirements.txt`**

```
streamlit>=1.32.0
crawl4ai>=0.3.5
scrapy>=2.11.0
scrapy-playwright>=0.0.34
playwright>=1.42.0
redis>=5.0.0
beautifulsoup4>=4.12.0
html2text>=2024.2.26
pyyaml>=6.0.1
responses>=0.25.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
fakeredis>=2.21.0
pytest-mock>=3.12.0
responses>=0.25.0
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: Create `scraper/__init__.py` and `tests/__init__.py`** (both empty files)

- [ ] **Step 5: Create `tests/conftest.py`**

```python
import pytest
import fakeredis
from datetime import datetime, timezone
from models import PageResult


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def sample_html():
    return """
    <html>
    <head>
        <title>Our Services</title>
        <meta name="description" content="We offer great services">
        <link rel="canonical" href="https://example.com/services">
    </head>
    <body>
        <nav>Nav links here</nav>
        <main>
            <h1>Our Services</h1>
            <h2>Consulting</h2>
            <p>We help businesses grow through strategic consulting.</p>
            <h2>Development</h2>
            <p>We build custom software solutions.</p>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """


@pytest.fixture
def sample_page_result():
    return PageResult(
        url="https://example.com/services",
        canonical_url="https://example.com/services",
        title="Our Services",
        description="We offer great services",
        language="en",
        raw_html="<h1>Our Services</h1><p>We help businesses grow.</p>",
        markdown="# Our Services\n\nWe help businesses grow.",
        page_type="services",
        word_count=6,
        scraped_at=datetime(2026, 3, 17, 10, 0, 0, tzinfo=timezone.utc),
        engine_used="crawl4ai",
        status="success",
    )
```

- [ ] **Step 6: Commit scaffold**

```bash
git add requirements.txt requirements-dev.txt pytest.ini scraper/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: project scaffold — requirements, pytest config, fixtures"
```

---

## Task 2: `models.py` — PageResult Dataclass

**Files:**
- Create: `models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py
from datetime import datetime, timezone
from models import PageResult


def test_page_result_required_field():
    result = PageResult(url="https://example.com")
    assert result.url == "https://example.com"


def test_page_result_defaults():
    result = PageResult(url="https://example.com")
    assert result.canonical_url == ""
    assert result.title == ""
    assert result.description == ""
    assert result.language == ""
    assert result.headings == []
    assert result.raw_html == ""
    assert result.markdown == ""
    assert result.page_type == "other"
    assert result.word_count == 0
    assert result.engine_used == ""
    assert result.status == "failed"
    assert result.skip_reason == ""
    assert isinstance(result.scraped_at, datetime)


def test_page_result_scraped_at_is_utc():
    result = PageResult(url="https://example.com")
    assert result.scraped_at.tzinfo == timezone.utc


def test_page_result_headings_is_not_shared():
    """Each instance must have its own headings list (mutable default trap)."""
    a = PageResult(url="https://example.com/a")
    b = PageResult(url="https://example.com/b")
    a.headings.append({"h1": "Title"})
    assert b.headings == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Implement `models.py`**

```python
# models.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: PageResult dataclass with defaults and UTC timestamp"
```

---

## Task 3: `scraper/snooper.py` — Pre-Crawl Intelligence

**Files:**
- Create: `scraper/snooper.py`
- Create: `tests/test_snooper.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_snooper.py
import pytest
import responses as resp_mock
from scraper.snooper import Snooper


@resp_mock.activate
def test_llm_txt_found_returns_url_list():
    resp_mock.add(
        resp_mock.GET,
        "https://example.com/llm.txt",
        body="https://example.com/about\nhttps://example.com/services\n",
        status=200,
    )
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/about", "https://example.com/services"]


@resp_mock.activate
def test_llm_txt_not_found_returns_root():
    resp_mock.add(resp_mock.GET, "https://example.com/llm.txt", status=404)
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/"]


@resp_mock.activate
def test_llm_txt_empty_falls_back_to_root():
    resp_mock.add(resp_mock.GET, "https://example.com/llm.txt", body="   \n\n", status=200)
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/"]


@resp_mock.activate
def test_robots_txt_disallowed_path():
    robots = "User-agent: *\nDisallow: /admin/\nDisallow: /private/\nCrawl-delay: 2\n"
    resp_mock.add(resp_mock.GET, "https://example.com/robots.txt", body=robots, status=200)
    snooper = Snooper("https://example.com")
    snooper.load_robots()
    assert snooper.is_disallowed("https://example.com/admin/dashboard")
    assert snooper.is_disallowed("https://example.com/private/data")
    assert not snooper.is_disallowed("https://example.com/about")
    assert snooper.crawl_delay == 2.0


@resp_mock.activate
def test_robots_txt_missing_uses_default_delay():
    resp_mock.add(resp_mock.GET, "https://example.com/robots.txt", status=404)
    snooper = Snooper("https://example.com")
    snooper.load_robots()
    assert snooper.crawl_delay == 1.0


def test_is_external_off_domain():
    snooper = Snooper("https://example.com")
    assert snooper.is_external("https://linkedin.com/company/example")
    assert snooper.is_external("https://twitter.com/example")
    assert snooper.is_external("https://www.instagram.com/example")


def test_is_external_same_domain_false():
    snooper = Snooper("https://example.com")
    assert not snooper.is_external("https://example.com/about")
    assert not snooper.is_external("https://www.example.com/services")


def test_has_noindex_true():
    snooper = Snooper("https://example.com")
    html = '<meta name="robots" content="noindex, nofollow">'
    assert snooper.has_noindex(html)


def test_has_noindex_false():
    snooper = Snooper("https://example.com")
    assert not snooper.has_noindex("<html><body><p>Normal page</p></body></html>")


def test_has_nofollow_true():
    snooper = Snooper("https://example.com")
    html = '<meta name="robots" content="nofollow">'
    assert snooper.has_nofollow(html)


def test_has_nofollow_false():
    snooper = Snooper("https://example.com")
    assert not snooper.has_nofollow('<meta name="robots" content="index, follow">')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_snooper.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.snooper'`

- [ ] **Step 3: Implement `scraper/snooper.py`**

```python
# scraper/snooper.py
import re
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class Snooper:
    """Pre-crawl intelligence: llm.txt, robots.txt, noindex/nofollow detection."""

    USER_AGENT = "Business-Scraper/1.0"

    def __init__(self, start_url: str, default_delay: float = 1.0):
        parsed = urlparse(start_url)
        self.scheme = parsed.scheme
        self.domain = parsed.netloc.lstrip("www.")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.crawl_delay = default_delay
        self._rp = urllib.robotparser.RobotFileParser()

    # ------------------------------------------------------------------
    # Seed URL resolution
    # ------------------------------------------------------------------

    def get_seed_urls(self) -> list[str]:
        """Return URL list from llm.txt, or [root] if not found."""
        try:
            r = requests.get(
                f"{self.base_url}/llm.txt",
                headers={"User-Agent": self.USER_AGENT},
                timeout=10,
            )
            if r.status_code == 200:
                urls = [u.strip() for u in r.text.splitlines() if u.strip().startswith("http")]
                if urls:
                    return urls
        except requests.RequestException:
            pass
        return [f"{self.base_url}/"]

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------

    def load_robots(self) -> None:
        """Fetch and parse robots.txt; set crawl_delay."""
        robots_url = f"{self.base_url}/robots.txt"
        self._rp.set_url(robots_url)
        try:
            self._rp.read()
            delay = self._rp.crawl_delay(self.USER_AGENT) or self._rp.crawl_delay("*")
            if delay:
                self.crawl_delay = float(delay)
        except Exception:
            pass  # robots.txt unreachable — use default delay

    def is_disallowed(self, url: str) -> bool:
        return not self._rp.can_fetch(self.USER_AGENT, url)

    # ------------------------------------------------------------------
    # External URL detection
    # ------------------------------------------------------------------

    def is_external(self, url: str) -> bool:
        parsed = urlparse(url)
        url_domain = parsed.netloc.lstrip("www.")
        return url_domain != self.domain

    # ------------------------------------------------------------------
    # Per-page meta checks
    # ------------------------------------------------------------------

    def has_noindex(self, html: str) -> bool:
        return self._robots_meta_has(html, "noindex")

    def has_nofollow(self, html: str) -> bool:
        return self._robots_meta_has(html, "nofollow")

    def _robots_meta_has(self, html: str, directive: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if not tag:
            return False
        content = tag.get("content", "").lower()
        return directive in content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_snooper.py -v
```

Expected: 12 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/snooper.py tests/test_snooper.py
git commit -m "feat: Snooper — llm.txt, robots.txt, noindex/nofollow detection"
```

---

## Task 4: `scraper/queue_manager.py` — Redis Crawl Queue

**Files:**
- Create: `scraper/queue_manager.py`
- Create: `tests/test_queue_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_queue_manager.py
import pytest
import fakeredis
from scraper.queue_manager import QueueManager


@pytest.fixture
def qm(fake_redis):
    return QueueManager("example.com", redis_client=fake_redis)


def test_enqueue_and_dequeue(qm):
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/services")
    assert qm.dequeue() == "https://example.com/about"
    assert qm.dequeue() == "https://example.com/services"
    assert qm.dequeue() is None


def test_enqueue_deduplicates_same_url(qm):
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/about")
    assert qm.dequeue() == "https://example.com/about"
    assert qm.dequeue() is None


def test_enqueue_normalizes_trailing_slash(qm):
    qm.enqueue("https://example.com/about/")
    qm.enqueue("https://example.com/about")
    assert qm.dequeue() is not None
    assert qm.dequeue() is None  # second was a duplicate after normalisation


def test_normalize_url_sorts_query_params(qm):
    norm = qm.normalize("https://example.com/page?b=2&a=1")
    assert norm == "https://example.com/page?a=1&b=2"


def test_normalize_url_lowercases_domain(qm):
    norm = qm.normalize("https://EXAMPLE.COM/About")
    assert norm == "https://example.com/About"


def test_mark_visited_and_is_visited(qm):
    qm.mark_visited("https://example.com/page")
    assert qm.is_visited("https://example.com/page")
    assert not qm.is_visited("https://example.com/other")


def test_enqueue_does_not_mark_as_scraped(qm):
    """Enqueueing a URL must NOT mark it as scraped (two-set design)."""
    qm.enqueue("https://example.com/about")
    assert not qm.is_visited("https://example.com/about")  # not yet scraped
    qm.mark_visited("https://example.com/about")
    assert qm.is_visited("https://example.com/about")  # now scraped


def test_content_hash_dedup(qm):
    assert not qm.is_duplicate_content("abc123hash")
    qm.add_content_hash("abc123hash")
    assert qm.is_duplicate_content("abc123hash")


def test_save_and_get_external_link(qm):
    qm.save_external("https://linkedin.com/company/example")
    qm.save_external("https://linkedin.com/company/example")  # duplicate
    qm.save_external("https://twitter.com/example")
    links = qm.get_external_links()
    assert "linkedin.com" in links
    assert len(links["linkedin.com"]) == 1  # deduped
    assert "twitter.com" in links


def test_log_line_stored(qm):
    qm.log("[OK] /about [crawl4ai] 500w")
    qm.log("[OK] /services [crawl4ai] 800w")
    lines = qm.get_log_lines(50)
    assert "[OK] /about [crawl4ai] 500w" in lines


def test_update_and_get_meta(qm):
    qm.update_meta(pages_done=5, pages_found=20, total_words=4000)
    meta = qm.get_meta()
    assert meta["pages_done"] == "5"
    assert meta["pages_found"] == "20"
    assert meta["total_words"] == "4000"


def test_has_existing_state(qm):
    assert not qm.has_existing_state()
    qm.enqueue("https://example.com/")
    assert qm.has_existing_state()


def test_flush_clears_all_keys(qm):
    qm.enqueue("https://example.com/")
    qm.mark_visited("https://example.com/about")
    qm.flush()
    assert not qm.has_existing_state()
    assert not qm.is_visited("https://example.com/about")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_queue_manager.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.queue_manager'`

- [ ] **Step 3: Implement `scraper/queue_manager.py`**

```python
# scraper/queue_manager.py
import hashlib
from urllib.parse import urlparse, urlencode, parse_qs

import redis as redis_lib


class QueueManager:
    """Redis-backed crawl queue with URL dedup, content hash dedup, and state persistence."""

    LOG_MAX = 500

    def __init__(self, domain: str, redis_client=None, redis_url: str = "redis://localhost:6379"):
        self.domain = domain
        self._r = redis_client or redis_lib.from_url(redis_url, decode_responses=True)
        self._keys = {
            "queue": f"{domain}:queue",
            "enqueued": f"{domain}:enqueued",   # dedup — prevents re-enqueueing
            "visited": f"{domain}:visited",      # URLs actually scraped (resume state)
            "content_hashes": f"{domain}:content_hashes",
            "failed": f"{domain}:failed",
            "external": f"{domain}:external",
            "log": f"{domain}:log",
            "meta": f"{domain}:meta",
        }

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    def enqueue(self, url: str) -> bool:
        """Add URL to queue if not already enqueued. Returns True if added.

        Uses a separate 'enqueued' set for dedup — does NOT mark the URL as
        scraped. Call mark_visited() after successful scraping.
        """
        norm = self.normalize(url)
        if self._r.sismember(self._keys["enqueued"], norm):
            return False
        self._r.sadd(self._keys["enqueued"], norm)
        self._r.rpush(self._keys["queue"], norm)
        return True

    def dequeue(self) -> str | None:
        return self._r.lpop(self._keys["queue"])

    def mark_visited(self, url: str) -> None:
        """Mark URL as actually scraped (called after scraping completes)."""
        self._r.sadd(self._keys["visited"], self.normalize(url))

    def is_visited(self, url: str) -> bool:
        """True if URL has been scraped (not just enqueued)."""
        return bool(self._r.sismember(self._keys["visited"], self.normalize(url)))

    def mark_failed(self, url: str) -> None:
        self._r.sadd(self._keys["failed"], self.normalize(url))

    # ------------------------------------------------------------------
    # Content dedup
    # ------------------------------------------------------------------

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def is_duplicate_content(self, hash_value: str) -> bool:
        return bool(self._r.sismember(self._keys["content_hashes"], hash_value))

    def add_content_hash(self, hash_value: str) -> None:
        self._r.sadd(self._keys["content_hashes"], hash_value)

    # ------------------------------------------------------------------
    # External links
    # ------------------------------------------------------------------

    def save_external(self, url: str) -> None:
        domain = urlparse(url).netloc.lstrip("www.")
        self._r.hset(self._keys["external"], f"{domain}::{url}", "1")

    def get_external_links(self) -> dict[str, list[str]]:
        raw = self._r.hkeys(self._keys["external"])
        result: dict[str, list[str]] = {}
        for entry in raw:
            domain, _, url = entry.partition("::")
            result.setdefault(domain, [])
            if url not in result[domain]:
                result[domain].append(url)
        return result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, line: str) -> None:
        self._r.lpush(self._keys["log"], line)
        self._r.ltrim(self._keys["log"], 0, self.LOG_MAX - 1)

    def get_log_lines(self, n: int) -> list[str]:
        return self._r.lrange(self._keys["log"], 0, n - 1)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def update_meta(self, **kwargs) -> None:
        self._r.hset(self._keys["meta"], mapping={k: str(v) for k, v in kwargs.items()})

    def get_meta(self) -> dict:
        return self._r.hgetall(self._keys["meta"])

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def has_existing_state(self) -> bool:
        return bool(self._r.llen(self._keys["queue"]) or self._r.scard(self._keys["enqueued"]))

    def flush(self) -> None:
        for key in self._keys.values():
            self._r.delete(key)

    # ------------------------------------------------------------------
    # URL normalisation
    # ------------------------------------------------------------------

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip())
        # Lowercase scheme and host
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        # Remove trailing slash from path (unless root)
        path = parsed.path.rstrip("/") or "/"
        # Sort query params
        query = urlencode(sorted(parse_qs(parsed.query, keep_blank_values=True).items()))
        return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_queue_manager.py -v
```

Expected: 14 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/queue_manager.py tests/test_queue_manager.py
git commit -m "feat: QueueManager — Redis queue, URL/content dedup, log, meta"
```

---

## Task 5: `scraper/page_processor.py` — Markdown + Frontmatter

**Files:**
- Create: `scraper/page_processor.py`
- Create: `tests/test_page_processor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_page_processor.py
import pytest
from scraper.page_processor import PageProcessor
from models import PageResult


@pytest.fixture
def processor():
    return PageProcessor()


# --- page_type detection ---

def test_page_type_homepage(processor):
    assert processor.detect_page_type("https://example.com/") == "homepage"


def test_page_type_about(processor):
    assert processor.detect_page_type("https://example.com/about-us") == "about"
    assert processor.detect_page_type("https://example.com/our-team") == "about"
    assert processor.detect_page_type("https://example.com/company/who-we-are") == "about"


def test_page_type_services(processor):
    assert processor.detect_page_type("https://example.com/services/consulting") == "services"
    assert processor.detect_page_type("https://example.com/our-solutions") == "services"


def test_page_type_blog(processor):
    assert processor.detect_page_type("https://example.com/blog/my-post") == "blog"
    assert processor.detect_page_type("https://example.com/news/update") == "blog"
    assert processor.detect_page_type("https://example.com/insights/2026") == "blog"


def test_page_type_case_study(processor):
    assert processor.detect_page_type("https://example.com/case-studies/acme") == "case-study"
    assert processor.detect_page_type("https://example.com/work/project-x") == "case-study"


def test_page_type_contact(processor):
    assert processor.detect_page_type("https://example.com/contact") == "contact"
    assert processor.detect_page_type("https://example.com/get-in-touch") == "contact"


def test_page_type_other(processor):
    assert processor.detect_page_type("https://example.com/legal/privacy") == "other"


def test_page_type_priority_homepage_over_contact(processor):
    # Root path wins homepage regardless of anything else
    assert processor.detect_page_type("https://example.com/") == "homepage"


# --- heading extraction ---

def test_extract_headings_h1_and_h2(processor):
    html = "<h1>Main Title</h1><h2>Section A</h2><h2>Section B</h2>"
    result = processor.extract_headings(html)
    assert result == [{"h1": "Main Title"}, {"h2": "Section A"}, {"h2": "Section B"}]


def test_extract_headings_empty_when_none(processor):
    assert processor.extract_headings("<p>No headings</p>") == []


def test_extract_headings_preserves_order(processor):
    html = "<h2>First</h2><h1>Second</h1><h2>Third</h2>"
    result = processor.extract_headings(html)
    assert result == [{"h2": "First"}, {"h1": "Second"}, {"h2": "Third"}]


# --- word count ---

def test_word_count(processor):
    assert processor.count_words("one two three") == 3
    assert processor.count_words("  hello   world  ") == 2
    assert processor.count_words("") == 0


# --- full process() ---

def test_process_injects_frontmatter(processor, sample_page_result):
    result = processor.process(sample_page_result)
    assert result.markdown.startswith("---\n")
    assert "url: https://example.com/services\n" in result.markdown
    assert "page_type: services\n" in result.markdown
    assert "engine_used: crawl4ai\n" in result.markdown


def test_process_frontmatter_ends_with_separator(processor, sample_page_result):
    result = processor.process(sample_page_result)
    parts = result.markdown.split("---\n", 2)
    assert len(parts) == 3  # opening ---, frontmatter, closing ---


def test_process_sets_word_count(processor):
    result = PageResult(
        url="https://example.com",
        markdown="one two three four five",
    )
    processed = processor.process(result)
    assert processed.word_count == 5


def test_process_detects_page_type(processor):
    result = PageResult(url="https://example.com/services/consulting", markdown="content")
    processed = processor.process(result)
    assert processed.page_type == "services"


def test_process_extracts_headings(processor):
    result = PageResult(
        url="https://example.com/about",
        raw_html="<h1>About Us</h1><h2>Our Story</h2>",
        markdown="# About Us\n\n## Our Story",
    )
    processed = processor.process(result)
    assert {"h1": "About Us"} in processed.headings
    assert {"h2": "Our Story"} in processed.headings
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_page_processor.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.page_processor'`

- [ ] **Step 3: Implement `scraper/page_processor.py`**

```python
# scraper/page_processor.py
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup

from models import PageResult

# page_type patterns: (regex, page_type) in priority order
_PAGE_TYPE_PATTERNS = [
    (r"^/$", "homepage"),
    (r"/(about|team|who-we-are|our-story|company)", "about"),
    (r"/(service|solution|what-we-do|offering|product)", "services"),
    (r"/(blog|news|insight|article|post|update)", "blog"),
    (r"/(case-stud|work|portfolio|project|client)", "case-study"),
    (r"/(contact|get-in-touch|reach-us)", "contact"),
]


class PageProcessor:
    """Injects YAML frontmatter, detects page_type, extracts headings, calculates word count."""

    def process(self, result: PageResult) -> PageResult:
        """Enrich a PageResult with frontmatter, page_type, headings, word_count."""
        result.page_type = self.detect_page_type(result.url)
        result.headings = self.extract_headings(result.raw_html)
        result.word_count = self.count_words(result.markdown)

        frontmatter = self._build_frontmatter(result)
        result.markdown = f"---\n{frontmatter}---\n\n{result.markdown}"
        return result

    def detect_page_type(self, url: str) -> str:
        path = urlparse(url).path.lower()
        for pattern, page_type in _PAGE_TYPE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                return page_type
        return "other"

    def extract_headings(self, html: str) -> list[dict]:
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        headings = []
        for tag in soup.find_all(["h1", "h2"]):
            text = tag.get_text(strip=True)
            if text:
                headings.append({tag.name: text})
        return headings

    def count_words(self, text: str) -> int:
        return len(text.split()) if text.strip() else 0

    def _build_frontmatter(self, result: PageResult) -> str:
        data = {
            "url": result.url,
            "canonical_url": result.canonical_url or result.url,
            "title": result.title,
            "description": result.description,
            "language": result.language,
            "page_type": result.page_type,
            "domain": urlparse(result.url).netloc,
            "scraped_at": result.scraped_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "word_count": result.word_count,
            "engine_used": result.engine_used,
            "headings": result.headings,
        }
        return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_page_processor.py -v
```

Expected: 20 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/page_processor.py tests/test_page_processor.py
git commit -m "feat: PageProcessor — frontmatter injection, page_type, headings, word count"
```

---

## Task 6: `scraper/crawl4ai_engine.py` — Primary Engine

**Files:**
- Create: `scraper/crawl4ai_engine.py`
- Create: `tests/test_crawl4ai_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crawl4ai_engine.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scraper.crawl4ai_engine import Crawl4AIEngine
from models import PageResult


@pytest.fixture
def engine():
    return Crawl4AIEngine()


@pytest.mark.asyncio
async def test_scrape_success_returns_page_result(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Services\n\nWe help businesses."
    mock_result.cleaned_html = "<h1>Services</h1><p>We help businesses.</p>"
    mock_result.metadata = {
        "title": "Services",
        "description": "We help",
        "language": "en",
        "canonical": "https://example.com/services",
    }
    mock_result.links = {"internal": [{"href": "https://example.com/about"}], "external": []}

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/services")

    assert isinstance(result, PageResult)
    assert result.status == "success"
    assert result.engine_used == "crawl4ai"
    assert result.title == "Services"
    assert "Services" in result.markdown
    assert "https://example.com/about" in links


@pytest.mark.asyncio
async def test_scrape_failure_returns_failed_result(engine):
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.markdown = ""
    mock_result.error_message = "Connection refused"

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/broken")

    assert result.status == "failed"
    assert result.skip_reason == "crawl4ai error: Connection refused"
    assert links == []


@pytest.mark.asyncio
async def test_scrape_empty_content_returns_failed(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "   "  # whitespace only
    mock_result.cleaned_html = ""
    mock_result.metadata = {}
    mock_result.links = {"internal": [], "external": []}

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/empty")

    assert result.status == "failed"
    assert result.skip_reason == "crawl4ai empty"


@pytest.mark.asyncio
async def test_scrape_extracts_internal_links_only(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Page\n\nContent here."
    mock_result.cleaned_html = "<h1>Page</h1>"
    mock_result.metadata = {"title": "Page", "description": "", "language": "en", "canonical": ""}
    mock_result.links = {
        "internal": [
            {"href": "https://example.com/about"},
            {"href": "https://example.com/services"},
        ],
        "external": [{"href": "https://linkedin.com/company/example"}],
    }

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/page")

    assert "https://example.com/about" in links
    assert "https://example.com/services" in links
    assert "https://linkedin.com/company/example" not in links
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_crawl4ai_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.crawl4ai_engine'`

- [ ] **Step 3: Implement `scraper/crawl4ai_engine.py`**

```python
# scraper/crawl4ai_engine.py
import asyncio

from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from models import PageResult

_SCRAPE_TIMEOUT = 30  # seconds


class Crawl4AIEngine:
    """Primary scraping engine using Crawl4AI + Playwright."""

    USER_AGENT = "Business-Scraper/1.0"

    async def scrape(self, url: str) -> tuple[PageResult, list[str]]:
        """
        Scrape a single URL.
        Returns (PageResult, list_of_internal_links).
        PageResult.status == 'failed' if scrape unsuccessful or empty.
        """
        result = PageResult(url=url, engine_used="crawl4ai")
        links: list[str] = []

        try:
            async with AsyncWebCrawler(
                user_agent=self.USER_AGENT,
                headless=True,
                verbose=False,
            ) as crawler:
                crawl_result = await asyncio.wait_for(
                    crawler.arun(
                        url=url,
                        cache_mode=CacheMode.DISABLED,
                        word_count_threshold=50,
                        content_filter=PruningContentFilter(),
                        markdown_generator=DefaultMarkdownGenerator(options={"fit_markdown": True}),
                    ),
                    timeout=_SCRAPE_TIMEOUT,
                )

            if not crawl_result.success:
                result.status = "failed"
                result.skip_reason = f"crawl4ai error: {getattr(crawl_result, 'error_message', 'unknown')}"
                return result, links

            if not crawl_result.markdown or not crawl_result.markdown.strip():
                result.status = "failed"
                result.skip_reason = "crawl4ai empty"
                return result, links

            meta = crawl_result.metadata or {}
            result.title = meta.get("title", "")
            result.description = meta.get("description", "")
            result.language = meta.get("language", "")
            result.canonical_url = meta.get("canonical", "") or url
            result.raw_html = crawl_result.cleaned_html or ""
            result.markdown = crawl_result.markdown
            result.status = "success"

            internal = crawl_result.links.get("internal", [])
            links = [lnk["href"] for lnk in internal if lnk.get("href", "").startswith("http")]

        except asyncio.TimeoutError:
            result.status = "failed"
            result.skip_reason = "crawl4ai timeout"
        except Exception as exc:
            result.status = "failed"
            result.skip_reason = f"crawl4ai error: {exc}"

        return result, links
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_crawl4ai_engine.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/crawl4ai_engine.py tests/test_crawl4ai_engine.py
git commit -m "feat: Crawl4AIEngine — primary async scraper with Playwright"
```

---

## Task 7: `scraper/scrapy_worker.py` + `scraper/scrapy_engine.py` — Fallback Engine

**Files:**
- Create: `scraper/scrapy_worker.py`
- Create: `scraper/scrapy_engine.py`
- Create: `tests/test_scrapy_engine.py`

> **Why subprocess?** Scrapy's Twisted reactor can only start once per process. Running Scrapy in a subprocess completely avoids this constraint — each `scrapy_engine.scrape()` call spawns a fresh process with its own reactor.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scrapy_engine.py
import json
import pytest
from unittest.mock import patch, MagicMock
from scraper.scrapy_engine import ScrapyEngine
from models import PageResult

SAMPLE_OUTPUT = json.dumps({
    "url": "https://example.com/services",
    "title": "Services",
    "description": "We do things",
    "language": "en",
    "canonical_url": "https://example.com/services",
    "raw_html": "<h1>Services</h1><p>We do things</p>",
    "markdown": "# Services\n\nWe do things",
    "status": "success",
})


@pytest.fixture
def engine():
    return ScrapyEngine()


def test_scrape_success_parses_json_output(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=SAMPLE_OUTPUT,
            stderr="",
        )
        result = engine.scrape("https://example.com/services")

    assert isinstance(result, PageResult)
    assert result.status == "success"
    assert result.engine_used == "scrapy"
    assert result.title == "Services"
    assert "Services" in result.markdown


def test_scrape_subprocess_failure_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Spider error",
        )
        result = engine.scrape("https://example.com/broken")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()


def test_scrape_timeout_returns_failed(engine):
    import subprocess
    with patch("scraper.scrapy_engine.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 20)):
        result = engine.scrape("https://example.com/slow")

    assert result.status == "failed"
    assert "timeout" in result.skip_reason.lower()


def test_scrape_sets_engine_used(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_OUTPUT, stderr="")
        result = engine.scrape("https://example.com/services")

    assert result.engine_used == "scrapy"


def test_scrape_invalid_json_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        result = engine.scrape("https://example.com/bad")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scrapy_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.scrapy_engine'`

- [ ] **Step 3: Implement `scraper/scrapy_worker.py`**

```python
# scraper/scrapy_worker.py
"""
Standalone Scrapy subprocess worker.
Usage: python scraper/scrapy_worker.py <url>
Prints a single JSON object to stdout.
"""
import json
import sys
import html2text
import scrapy
from scrapy.crawler import CrawlerProcess
from bs4 import BeautifulSoup


class SinglePageSpider(scrapy.Spider):
    name = "single_page"
    custom_settings = {
        "LOG_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 20,
        "DEPTH_LIMIT": 1,
        "USER_AGENT": "Business-Scraper/1.0",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(self, url: str, result_container: list, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = [url]
        self.result_container = result_container

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove nav, footer, ads
        for tag in soup.select("nav, footer, header, .cookie-banner, #cookie-notice, .ads"):
            tag.decompose()

        clean_html = str(soup)

        converter = html2text.HTML2Text()
        converter.ignore_images = False
        converter.body_width = 0
        converter.unicode_snob = True
        markdown = converter.handle(clean_html)

        title = response.css("title::text").get("").strip()
        description = response.css('meta[name="description"]::attr(content)').get("").strip()
        canonical = response.css('link[rel="canonical"]::attr(href)').get("").strip()
        lang = response.css("html::attr(lang)").get("").strip()

        self.result_container.append({
            "url": response.url,
            "title": title,
            "description": description,
            "language": lang,
            "canonical_url": canonical or response.url,
            "raw_html": clean_html,
            "markdown": markdown,
            "status": "success",
        })


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "failed", "skip_reason": "no URL provided"}))
        sys.exit(1)

    target_url = sys.argv[1]
    container: list = []

    process = CrawlerProcess()
    process.crawl(SinglePageSpider, url=target_url, result_container=container)
    process.start()

    if container:
        print(json.dumps(container[0]))
    else:
        print(json.dumps({"url": target_url, "status": "failed", "skip_reason": "scrapy no result"}))
```

- [ ] **Step 4: Implement `scraper/scrapy_engine.py`**

```python
# scraper/scrapy_engine.py
import json
import subprocess
import sys
from pathlib import Path

from models import PageResult

_WORKER = str(Path(__file__).parent / "scrapy_worker.py")
_TIMEOUT = 25  # seconds (scrapy internal timeout 20s + buffer)


class ScrapyEngine:
    """Fallback scraper: spawns scrapy_worker.py as a subprocess."""

    def scrape(self, url: str) -> PageResult:
        result = PageResult(url=url, engine_used="scrapy")
        try:
            proc = subprocess.run(
                [sys.executable, _WORKER, url],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            if proc.returncode != 0:
                result.status = "failed"
                result.skip_reason = f"scrapy exit {proc.returncode}: {proc.stderr[:200]}"
                return result

            data = json.loads(proc.stdout)
            result.title = data.get("title", "")
            result.description = data.get("description", "")
            result.language = data.get("language", "")
            result.canonical_url = data.get("canonical_url", "") or url
            result.raw_html = data.get("raw_html", "")
            result.markdown = data.get("markdown", "")
            result.status = data.get("status", "failed")
            if result.status != "success":
                result.skip_reason = data.get("skip_reason", "scrapy failed")

        except subprocess.TimeoutExpired:
            result.status = "failed"
            result.skip_reason = "scrapy timeout"
        except json.JSONDecodeError as exc:
            result.status = "failed"
            result.skip_reason = f"scrapy bad json: {exc}"
        except Exception as exc:
            result.status = "failed"
            result.skip_reason = f"scrapy error: {exc}"

        return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_scrapy_engine.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add scraper/scrapy_worker.py scraper/scrapy_engine.py tests/test_scrapy_engine.py
git commit -m "feat: ScrapyEngine — subprocess fallback scraper via scrapy_worker.py"
```

---

## Task 8: `scraper/hybrid_scraper.py` — Orchestrator

**Files:**
- Create: `scraper/hybrid_scraper.py`
- Create: `tests/test_hybrid_scraper.py`

- [ ] **Step 1: Write failing tests**

```python
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
         patch("scraper.hybrid_scraper.ScrapyEngine") as MockFallback, \
         patch("scraper.hybrid_scraper.asyncio.get_event_loop"):
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

    assert len([r for r in results if r.status == "success"]) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hybrid_scraper.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.hybrid_scraper'`

- [ ] **Step 3: Implement `scraper/hybrid_scraper.py`**

```python
# scraper/hybrid_scraper.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

from models import PageResult
from scraper.crawl4ai_engine import Crawl4AIEngine
from scraper.scrapy_engine import ScrapyEngine
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper
from scraper.page_processor import PageProcessor

_MAX_DEPTH = 10


class HybridScraper:
    """Async generator: Crawl4AI primary → Scrapy fallback per URL."""

    def __init__(self, queue: QueueManager, snooper: Snooper,
                 max_pages: int = 500, cancel_flag: list | None = None):
        self.queue = queue
        self.snooper = snooper
        self.max_pages = max_pages
        self.cancel_flag = cancel_flag or []  # set cancel_flag.append(True) to stop
        self._processor = PageProcessor()
        self._primary = Crawl4AIEngine()
        self._fallback = ScrapyEngine()
        self._pages_done = 0

    async def crawl(self, start_url: str) -> AsyncGenerator[PageResult, None]:
        with ThreadPoolExecutor(max_workers=1) as pool:
            while True:
                if self.cancel_flag:
                    break
                if self._pages_done >= self.max_pages:
                    break

                url = self.queue.dequeue()
                if url is None:
                    break

                result = await self._scrape_url(url, pool)
                if result.status == "success":
                    result = self._processor.process(result)
                    content_hash = self.queue.content_hash(result.markdown)
                    if self.queue.is_duplicate_content(content_hash):
                        result.skip_reason = "duplicate-content"
                    else:
                        self.queue.add_content_hash(content_hash)

                # Mark as actually scraped (two-set dedup: enqueued ≠ visited)
                if result.status in ("success", "failed"):
                    self.queue.mark_visited(url)

                self._pages_done += 1
                self.queue.update_meta(
                    pages_done=self._pages_done,
                    total_words=int(self.queue.get_meta().get("total_words", 0)) + result.word_count,
                )
                self.queue.log(self._format_log(result))

                yield result

                if self.snooper.crawl_delay > 0:
                    await asyncio.sleep(self.snooper.crawl_delay)

    async def _scrape_url(self, url: str, pool: ThreadPoolExecutor) -> PageResult:
        # Pre-flight checks
        if self.snooper.is_disallowed(url):
            return PageResult(url=url, status="skipped", skip_reason="robots disallowed")
        if self.snooper.is_external(url):
            self.queue.save_external(url)
            return PageResult(url=url, status="skipped", skip_reason="external url")

        # Primary: Crawl4AI
        result, links = await self._primary.scrape(url)

        if result.status == "success":
            if self.snooper.has_noindex(result.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex")
            if not self.snooper.has_nofollow(result.raw_html):
                self._enqueue_links(links, url)
            return result

        # Fallback: Scrapy (blocking, in thread)
        loop = asyncio.get_event_loop()
        fallback = await loop.run_in_executor(pool, self._fallback.scrape, url)
        if fallback.status == "success":
            if self.snooper.has_noindex(fallback.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex")
            return fallback

        # Both failed
        self.queue.mark_failed(url)
        return PageResult(url=url, status="failed", skip_reason="both engines failed")

    def _enqueue_links(self, links: list[str], source_url: str) -> None:
        for link in links:
            if not self.snooper.is_external(link) and not self.snooper.is_disallowed(link):
                self.queue.enqueue(link)
        self.queue.update_meta(pages_found=self.queue._r.scard(
            self.queue._keys["enqueued"]  # count discovered URLs, not scraped
        ))

    def _format_log(self, result: PageResult) -> str:
        if result.status == "success":
            tag = "[WARN]" if result.engine_used == "scrapy" else "[OK]  "
            return f"{tag} {result.url} [{result.engine_used}] {result.word_count}w"
        elif result.status == "skipped":
            return f"[SKIP] {result.url}  {result.skip_reason}"
        else:
            return f"[FAIL] {result.url}  {result.skip_reason}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hybrid_scraper.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/hybrid_scraper.py tests/test_hybrid_scraper.py
git commit -m "feat: HybridScraper — async generator with Crawl4AI→Scrapy fallback"
```

---

## Task 9: `scraper/exporter.py` — Zip Output Builder

**Files:**
- Create: `scraper/exporter.py`
- Create: `tests/test_exporter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_exporter.py
import io
import zipfile
from datetime import datetime, timezone
import pytest
from models import PageResult
from scraper.exporter import Exporter


@pytest.fixture
def pages():
    return [
        PageResult(
            url="https://example.com/",
            title="Home",
            markdown="---\npage_type: homepage\n---\n\n# Welcome",
            page_type="homepage",
            word_count=10,
            engine_used="crawl4ai",
            status="success",
            scraped_at=datetime(2026, 3, 17, tzinfo=timezone.utc),
        ),
        PageResult(
            url="https://example.com/services/consulting",
            title="Consulting",
            markdown="---\npage_type: services\n---\n\n# Consulting",
            page_type="services",
            word_count=50,
            engine_used="crawl4ai",
            status="success",
            scraped_at=datetime(2026, 3, 17, tzinfo=timezone.utc),
        ),
        PageResult(
            url="https://example.com/broken",
            status="failed",
            skip_reason="both engines failed",
        ),
    ]


@pytest.fixture
def external_links():
    return {
        "linkedin.com": ["https://linkedin.com/company/example"],
        "twitter.com": ["https://twitter.com/example"],
    }


def test_zip_contains_master_site_md(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert any("master_site.md" in n for n in names)


def test_zip_contains_individual_pages(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert any("individual_pages/" in n for n in names)
    assert any("homepage.md" in n for n in names)


def test_zip_contains_external_links(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "external_links" in n][0]).decode()
    assert "linkedin.com" in content
    assert "https://linkedin.com/company/example" in content


def test_zip_contains_crawl_report(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "crawl_report" in n][0]).decode()
    assert "2" in content   # 2 successful pages
    assert "1" in content   # 1 failed page


def test_slugify_url(pages, external_links):
    exporter = Exporter("example.com")
    assert exporter.slugify("https://example.com/services/consulting") == "services-consulting"
    assert exporter.slugify("https://example.com/") == "homepage"
    assert exporter.slugify("https://example.com/about-us/team") == "about-us-team"


def test_master_site_ordered_by_page_type(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "master_site" in n][0]).decode()
    # homepage should appear before services in master_site.md
    assert content.index("homepage") < content.index("services")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_exporter.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper.exporter'`

- [ ] **Step 3: Implement `scraper/exporter.py`**

```python
# scraper/exporter.py
import io
import re
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse

from models import PageResult

_PAGE_TYPE_ORDER = ["homepage", "about", "services", "blog", "case-study", "contact", "other"]


class Exporter:
    """Builds the output .zip with individual pages, master_site.md, reports."""

    def __init__(self, domain: str):
        self.domain = domain

    def build_zip(
        self,
        pages: list[PageResult],
        external_links: dict[str, list[str]],
        crawl_duration_seconds: float = 0.0,
    ) -> bytes:
        buf = io.BytesIO()
        successful = [p for p in pages if p.status == "success"]
        failed = [p for p in pages if p.status == "failed"]
        skipped = [p for p in pages if p.status == "skipped"]

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        prefix = f"{self.domain}-{date_str}"

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Individual pages
            for page in successful:
                slug = self.slugify(page.url)
                zf.writestr(f"{prefix}/individual_pages/{slug}.md", page.markdown)

            # master_site.md (sorted by page_type)
            sorted_pages = sorted(
                successful,
                key=lambda p: (_PAGE_TYPE_ORDER.index(p.page_type)
                               if p.page_type in _PAGE_TYPE_ORDER else 99, p.url)
            )
            master = "\n\n---\n\n".join(p.markdown for p in sorted_pages)
            zf.writestr(f"{prefix}/master_site.md", master)

            # external_links.md
            zf.writestr(f"{prefix}/external_links.md", self._build_external_links(external_links))

            # crawl_report.md
            zf.writestr(
                f"{prefix}/crawl_report.md",
                self._build_report(successful, failed, skipped, crawl_duration_seconds),
            )

        return buf.getvalue()

    def slugify(self, url: str) -> str:
        path = urlparse(url).path.strip("/")
        if not path:
            return "homepage"
        slug = re.sub(r"[^a-zA-Z0-9/-]", "", path)
        slug = slug.replace("/", "-").strip("-")
        return slug or "page"

    def _build_external_links(self, external_links: dict[str, list[str]]) -> str:
        if not external_links:
            return "# External Links\n\nNo external links found.\n"
        lines = ["# External Links\n"]
        for domain, urls in sorted(external_links.items()):
            lines.append(f"\n## {domain}\n")
            for url in urls:
                lines.append(f"- [{url}]({url})")
        return "\n".join(lines)

    def _build_report(
        self,
        successful: list[PageResult],
        failed: list[PageResult],
        skipped: list[PageResult],
        duration: float,
    ) -> str:
        total_words = sum(p.word_count for p in successful)
        crawl4ai_count = sum(1 for p in successful if p.engine_used == "crawl4ai")
        scrapy_count = sum(1 for p in successful if p.engine_used == "scrapy")

        skip_reasons: dict[str, int] = {}
        for p in skipped:
            skip_reasons[p.skip_reason] = skip_reasons.get(p.skip_reason, 0) + 1

        lines = [
            "# Crawl Report",
            "",
            f"**Domain:** {self.domain}",
            f"**Duration:** {duration:.1f}s",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|---|---|",
            f"| Pages scraped | {len(successful)} |",
            f"| Pages failed | {len(failed)} |",
            f"| Pages skipped | {len(skipped)} |",
            f"| Total word count | {total_words:,} |",
            f"| Crawl4AI | {crawl4ai_count} |",
            f"| Scrapy fallback | {scrapy_count} |",
            "",
            "## Skip Reasons",
            "",
        ]
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {count}")

        if failed:
            lines += ["", "## Failed URLs", ""]
            for p in failed:
                lines.append(f"- {p.url} ({p.skip_reason})")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_exporter.py -v
```

Expected: 6 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scraper/exporter.py tests/test_exporter.py
git commit -m "feat: Exporter — .zip with individual pages, master_site, report, external links"
```

---

## Task 10: `app.py` — Streamlit UI

**Files:**
- Create: `app.py`

> Note: Streamlit apps are integration-tested by running them, not unit-tested. This task has no unit tests. Manual verification steps are included.

- [ ] **Step 1: Implement `app.py`**

```python
# app.py
# IMPORTANT: All helper functions are defined BEFORE any Streamlit UI code
# that calls them. Streamlit reruns the entire script top-to-bottom on each
# interaction, so function definitions must precede their call sites.
import queue
import threading
import time
import asyncio
from urllib.parse import urlparse

import redis
import streamlit as st

from models import PageResult
from scraper.snooper import Snooper
from scraper.queue_manager import QueueManager
from scraper.hybrid_scraper import HybridScraper
from scraper.exporter import Exporter

REDIS_URL = "redis://redis:6379"


# ===========================================================================
# SECTION 1: Helper functions — all defined before any Streamlit UI code
# ===========================================================================

def _run_crawl(start_url: str, max_pages: int, rate_limit: float,
               result_queue: queue.Queue, cancel_flag: list) -> None:
    """Runs in a daemon thread with its own asyncio event loop.

    Threading model:
    - This function runs in a background daemon thread (started by _start_crawl).
    - It creates and owns its own asyncio event loop via asyncio.run().
    - Results are placed onto a thread-safe queue.Queue.
    - Streamlit polls this queue on each rerun (st.rerun()) — the thread is
      NOT affected by Streamlit reruns. Generator state lives in this thread.
    - cancel_flag is a shared mutable list; appending True signals cancellation.
    """
    async def _crawl():
        parsed = urlparse(start_url)
        domain = parsed.netloc.lstrip("www.")

        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        qm = QueueManager(domain, redis_client=redis_client)

        snooper = Snooper(start_url, default_delay=rate_limit)
        snooper.load_robots()
        snooper.crawl_delay = max(rate_limit, snooper.crawl_delay)

        seed_urls = snooper.get_seed_urls()
        for url in seed_urls:
            qm.enqueue(url)
        qm.update_meta(pages_found=len(seed_urls), pages_done=0, total_words=0)

        scraper = HybridScraper(qm, snooper, max_pages=max_pages, cancel_flag=cancel_flag)
        async for result in scraper.crawl(start_url):
            result_queue.put(result)

        result_queue.put(None)  # sentinel: crawl complete

    asyncio.run(_crawl())


def _start_crawl(url: str, max_pages: int, rate_limit: float, fresh: bool = True) -> None:
    """Reset session state and launch background crawl thread."""
    st.session_state.crawl_running = True
    st.session_state.results = []
    st.session_state.log_lines = []
    st.session_state.stats = {
        "scraped": 0, "failed": 0, "skipped": 0,
        "words": 0, "crawl4ai": 0, "scrapy": 0,
    }
    st.session_state.cancel_flag = []
    st.session_state.zip_bytes = None
    st.session_state.domain = urlparse(url).netloc.lstrip("www.")

    result_q: queue.Queue = queue.Queue()
    st.session_state.result_queue = result_q

    threading.Thread(
        target=_run_crawl,
        args=(url, max_pages, rate_limit, result_q, st.session_state.cancel_flag),
        daemon=True,
    ).start()


def _update_stats(result: PageResult) -> None:
    s = st.session_state.stats
    if result.status == "success":
        s["scraped"] += 1
        s["words"] += result.word_count
        s["scrapy" if result.engine_used == "scrapy" else "crawl4ai"] += 1
    elif result.status == "failed":
        s["failed"] += 1
    elif result.status == "skipped":
        s["skipped"] += 1


def _append_log(result: PageResult) -> None:
    if result.status == "success":
        tag = "[WARN]" if result.engine_used == "scrapy" else "[OK]  "
        line = f"{tag} {result.url} [{result.engine_used}] {result.word_count}w"
    elif result.status == "skipped":
        line = f"[SKIP] {result.url}  {result.skip_reason}"
    else:
        line = f"[FAIL] {result.url}  {result.skip_reason}"
    lines = [line] + st.session_state.log_lines
    st.session_state.log_lines = lines[:50]


def _build_zip() -> None:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        qm = QueueManager(st.session_state.domain, redis_client=redis_client)
        external = qm.get_external_links()
        exporter = Exporter(st.session_state.domain)
        st.session_state.zip_bytes = exporter.build_zip(st.session_state.results, external)
    except Exception as exc:
        st.error(f"Failed to build zip: {exc}")


# ===========================================================================
# SECTION 2: Streamlit UI — runs after all functions are defined above
# ===========================================================================

st.set_page_config(page_title="Business Scraper", layout="wide")
st.title("Business Scraper")
st.caption("Crawl a company website and download RAG-ready Markdown files.")

# --- Session state init (idempotent — runs every rerun) ---
_defaults = {
    "crawl_running": False,
    "results": [],
    "log_lines": [],
    "stats": {"scraped": 0, "failed": 0, "skipped": 0, "words": 0, "crawl4ai": 0, "scrapy": 0},
    "cancel_flag": [],
    "result_queue": None,
    "domain": "",
    "zip_bytes": None,
    "pending_resume": None,
}
for key, default in _defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- Input form ---
with st.form("crawl_form"):
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        url_input = st.text_input("Target URL", placeholder="https://example.com")
    with col2:
        max_pages = st.number_input("Max pages", min_value=10, max_value=5000, value=500, step=50)
    with col3:
        rate_limit = st.number_input("Rate limit (s)", min_value=0.5, max_value=10.0, value=1.0, step=0.5)
    submitted = st.form_submit_button("Start Crawl")

# --- Handle form submission (check for existing crawl state) ---
if submitted and url_input:
    parsed = urlparse(url_input)
    domain = parsed.netloc.lstrip("www.")
    try:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        qm_check = QueueManager(domain, redis_client=_redis)
        if qm_check.has_existing_state():
            st.session_state.pending_resume = {
                "url": url_input, "domain": domain,
                "max_pages": max_pages, "rate_limit": rate_limit,
            }
        else:
            st.session_state.pending_resume = None
            _start_crawl(url_input, int(max_pages), rate_limit)
    except Exception:
        _start_crawl(url_input, int(max_pages), rate_limit)

# --- Resume prompt ---
if st.session_state.pending_resume:
    pr = st.session_state.pending_resume
    st.info(f"Existing crawl found for **{pr['domain']}**. Resume or start fresh?")
    col_a, col_b = st.columns(2)
    if col_a.button("Resume"):
        _start_crawl(pr["url"], pr["max_pages"], pr["rate_limit"], fresh=False)
        st.session_state.pending_resume = None
    if col_b.button("Start Fresh"):
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        QueueManager(pr["domain"], redis_client=_redis).flush()
        _start_crawl(pr["url"], pr["max_pages"], pr["rate_limit"], fresh=True)
        st.session_state.pending_resume = None

# --- Live crawl polling ---
if st.session_state.crawl_running and st.session_state.result_queue:
    if st.button("Cancel"):
        st.session_state.cancel_flag.append(True)

    rq = st.session_state.result_queue
    batch = 0
    while batch < 10:
        try:
            result = rq.get_nowait()
            if result is None:
                st.session_state.crawl_running = False
                _build_zip()
                break
            st.session_state.results.append(result)
            _update_stats(result)
            _append_log(result)
            batch += 1
        except queue.Empty:
            break

    if st.session_state.crawl_running:
        time.sleep(0.3)
        st.rerun()

# --- Stats bar ---
s = st.session_state.stats
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Scraped", s["scraped"])
c2.metric("Failed", s["failed"])
c3.metric("Skipped", s["skipped"])
c4.metric("Words", f"{s['words']:,}")
c5.metric("Crawl4AI", s["crawl4ai"])
c6.metric("Scrapy fallback", s["scrapy"])

# --- Live feed ---
if st.session_state.log_lines:
    st.subheader("Live Feed")
    st.code("\n".join(st.session_state.log_lines), language=None)

# --- Download button ---
if st.session_state.zip_bytes:
    st.success(f"Crawl complete. {s['scraped']} pages scraped, {s['words']:,} words.")
    st.download_button(
        label="Download .zip",
        data=st.session_state.zip_bytes,
        file_name=f"{st.session_state.domain}-scraped.zip",
        mime="application/zip",
    )
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat: Streamlit UI — live feed, stats, background thread crawl, download"
```

---

## Task 11: Dockerfile + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim

# System dependencies for Playwright/Chromium
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Use python -m playwright to ensure correct package invocation
RUN python -m playwright install --with-deps chromium

COPY . .

RUN mkdir -p /app/output

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.address", "0.0.0.0", \
    "--server.port", "8501", \
    "--server.headless", "true"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    ports:
      - "8501:8501"
    volumes:
      - ./output:/app/output
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy
    stop_grace_period: 15s

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --save 60 1 --loglevel warning
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis_data:
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: Dockerfile + docker-compose.yml — Playwright/Chromium + Redis"
```

---

## Task 12: Full Test Suite + Docker Smoke Test

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests PASSED (no failures). Note: crawl4ai and scrapy tests use mocks — no real network calls.

- [ ] **Step 2: Build Docker image**

```bash
docker compose build
```

Expected: Build completes without error. Playwright/Chromium installs successfully.

- [ ] **Step 3: Start services**

```bash
docker compose up -d
```

Expected: Both `app` and `redis` containers start. `redis` healthcheck passes.

- [ ] **Step 4: Smoke test the UI**

Open `http://localhost:8501` in a browser.
- Enter `https://example.com` in the URL field
- Click Start Crawl
- Verify: live feed appears, stats update, no Python errors in terminal
- Wait for completion
- Verify: Download .zip button appears
- Download and inspect zip — should contain `individual_pages/`, `master_site.md`, `crawl_report.md`

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: complete Business Scraper v1.0 — all components integrated"
```

---

## Running Locally (without Docker)

```bash
# Install dependencies (requires Redis running locally)
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium

# Run tests
pytest tests/ -v

# Start Redis (or use Docker just for Redis)
docker run -d -p 6379:6379 redis:7-alpine

# Run app
REDIS_URL=redis://localhost:6379 streamlit run app.py
```
