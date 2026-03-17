# Business Scraper — Design Spec
**Date:** 2026-03-17
**Status:** Approved (v2 — post spec-review fixes)
**Purpose:** Dockerized web application that crawls a company website and converts all content into RAG-ready Markdown files for LLM consumption / vector DB ingestion.

---

## 1. Overview

Business Scraper takes a single company website URL, crawls its entire public domain (respecting ethical crawl rules), and produces clean, richly-annotated Markdown files optimized for RAG ingestion into a vector database.

**Primary use case:** Competitive intelligence and company due diligence — aggregate all public information from a company's website into structured, LLM-ready documents.

---

## 2. Architecture

```
business-scraper/
├── app.py                  # Streamlit UI + crawl orchestration
├── scraper/
│   ├── __init__.py
│   ├── snooper.py          # llm.txt / robots.txt / noindex checks
│   ├── queue_manager.py    # Redis crawl queue, dedup, state persistence
│   ├── crawl4ai_engine.py  # Primary scraping engine (Crawl4AI + Playwright)
│   ├── scrapy_engine.py    # Fallback scraping engine (Scrapy, thread pool)
│   ├── hybrid_scraper.py   # Orchestrates primary + fallback per URL
│   ├── page_processor.py   # HTML → clean Markdown + YAML frontmatter
│   └── exporter.py         # Builds .zip output package
├── models.py               # PageResult dataclass (shared interface)
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### High-Level Flow

```
User enters URL
  → Snooper checks llm.txt / robots.txt
  → QueueManager seeds Redis with seed URLs
  → HybridScraper generator yields PageResults one at a time
      → Crawl4AI attempts scrape (primary)
      → On failure → Scrapy fallback (ThreadPoolExecutor)
  → PageProcessor converts result to Markdown + rich YAML frontmatter
  → Exporter writes individual pages + master_site.md
  → Streamlit re-runs on each yielded result, shows live feed + stats
  → Download .zip when crawl completes
```

---

## 3. Components

### 3.1 `models.py` — Shared Data Contract

A single `PageResult` dataclass returned by both engines:

| Field | Type | Description |
|---|---|---|
| `url` | str | Final resolved URL |
| `canonical_url` | str | Canonical URL from meta tag |
| `title` | str | Page `<title>` |
| `description` | str | Meta description |
| `language` | str | Detected language (ISO 639-1) |
| `headings` | list[dict] | Ordered flat list of heading dicts: `[{"h1": "..."}, {"h2": "..."}]`. Empty list if no headings found. No nesting. |
| `raw_html` | str | Raw HTML before processing |
| `markdown` | str | Converted Markdown content |
| `page_type` | str | Auto-detected: homepage/about/services/blog/case-study/contact/other |
| `word_count` | int | Word count of extracted content |
| `scraped_at` | datetime | UTC timestamp |
| `engine_used` | str | `crawl4ai` or `scrapy` |
| `status` | str | `success` / `failed` / `skipped` |
| `skip_reason` | str | Reason if skipped/failed (empty string on success) |

### 3.2 `snooper.py` — Pre-Crawl Intelligence

Runs once before crawl begins; per-page meta checks run on each fetched page:

1. **`llm.txt` check** — GET `https://<domain>/llm.txt`. If found, parse URL list and use as seed queue directly (skip recursive crawl).
2. **`robots.txt` check** — Parse disallowed paths and `Crawl-delay`. Honour all directives. Store parsed rules for per-URL checks during crawl.
3. **Per-page noindex/nofollow** — Check `<meta name="robots" content="...">` on each fetched page:
   - `noindex` → skip page content, do not export
   - `nofollow` → do not follow outbound links from this page
4. **External URL detection** — Off-domain URLs (social platforms: LinkedIn, Instagram, Twitter/X, Facebook, YouTube, and any URL requiring login) are captured and grouped by domain in `external_links.md`, never queued for crawl. Duplicates are deduplicated. Format in output: `- [url](url)` grouped under `## linkedin.com`, `## instagram.com`, etc.

### 3.3 `queue_manager.py` — Crawl State via Redis

Redis data structures:

| Key | Type | Purpose |
|---|---|---|
| `{domain}:queue` | List | Pending URLs (LPUSH/RPOP) |
| `{domain}:visited` | Set | URL-normalised visited set (URL-level dedup) |
| `{domain}:content_hashes` | Set | SHA-256 of page content (within-session content dedup) |
| `{domain}:failed` | Set | URLs both engines failed on |
| `{domain}:external_links` | Hash | External URLs by domain: `{domain → [url, ...]}` |
| `{domain}:log` | List | Last 500 crawl log lines for UI display (LPUSH/LTRIM) |
| `{domain}:meta` | Hash | Crawl metadata: start_time, pages_done, pages_found, total_words |

**Resumability:** Crawl state survives container restarts. Re-entering the same domain resumes from where it left off. UI shows: *"Existing crawl found: 31/42 pages done. Resume or start fresh?"* Starting fresh flushes all domain keys before re-seeding.

**Deduplication rules:**
- URL dedup: same URL (normalised: lowercase, strip trailing slash, strip default ports, sort query params) is never scraped twice.
- Content dedup: if SHA-256 of extracted text matches a prior page in the same session, the page is logged as `[duplicate-content]` in `crawl_report.md` but still exported under its own filename (different URLs may have identical content for legitimate reasons).

**Rate limiting:** Simple linear delay — `asyncio.sleep(delay)` after each page scrape. Default: 1.0s. If `robots.txt` specifies a `Crawl-delay` greater than the user-configured value, the robots.txt value takes precedence. Delay stored in `{domain}:meta` as `crawl_delay`.

### 3.4 `hybrid_scraper.py` — Engine Orchestration

Implemented as an **async generator** that yields `PageResult` objects one at a time. This allows Streamlit to re-run on each result without blocking.

```python
async def crawl(start_url, config) -> AsyncGenerator[PageResult, None]:
    async with crawl4ai_engine as primary:
        with ThreadPoolExecutor(max_workers=1) as fallback_pool:
            while url := queue_manager.dequeue():
                # Pre-flight checks
                if robots_disallowed(url):
                    yield PageResult(url, status="skipped", skip_reason="robots disallowed")
                    continue
                if is_external(url):
                    queue_manager.save_external(url)
                    continue

                # Crawl4AI triggers fallback on:
                # - asyncio.TimeoutError after 30s
                # - HTTP 5xx
                # - result.markdown.strip() == ""
                # - CrawlerResult.success == False
                try:
                    result = await asyncio.wait_for(primary.scrape(url), timeout=30)
                    if result.success and result.markdown.strip():
                        yield process(result, engine="crawl4ai")
                        continue
                except (asyncio.TimeoutError, Exception):
                    pass

                # Scrapy fallback — blocking, runs in dedicated thread
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        fallback_pool, scrapy_engine.scrape, url
                    )
                    if result.success and result.markdown.strip():
                        yield process(result, engine="scrapy")
                        continue
                except Exception:
                    pass

                yield PageResult(url, status="failed", skip_reason="both engines failed")

                await asyncio.sleep(queue_manager.crawl_delay)
```

### 3.5 `crawl4ai_engine.py` — Primary Engine

- **Version:** `crawl4ai>=0.3.5` (stable Playwright lifecycle management)
- **Lifecycle:** Single `AsyncWebCrawler` instance created once as an async context manager, shared across all URLs in a crawl session. One browser, one context, sequential page scraping. Closed cleanly on exit.
- **Browser pool:** No parallelism — one page at a time (rate limiting + memory safety). Playwright browser is not restarted between URLs.
- **Configuration:**
  - `CacheMode.DISABLED` (always fresh)
  - `word_count_threshold=50` (skip near-empty pages)
  - `PruningContentFilter` to strip nav/footer/ads
  - `DefaultMarkdownGenerator` with `fit_markdown=True`
  - `User-Agent: Business-Scraper/1.0`
- **Link extraction:** All on-domain `<a href>` links extracted from each page and added to queue (unless `nofollow`).

### 3.6 `scrapy_engine.py` — Fallback Engine

- **Threading model:** A single `scrapy_engine.scrape(url)` call runs synchronously. Each call instantiates a fresh Scrapy `CrawlerProcess` with a single-URL spider in its own thread (via `ThreadPoolExecutor(max_workers=1)`). This avoids Twisted reactor conflicts — Scrapy's reactor is never reused across calls.
- **JS rendering:** `scrapy-playwright` enabled on the spider for JS-heavy pages.
- **Content extraction:** `BeautifulSoup` + `html2text` (same pipeline as `page_processor.py`).
- **Timeout:** 20 seconds (Scrapy `DOWNLOAD_TIMEOUT=20`).
- **Link following:** Disabled (`DEPTH_LIMIT=1`, `FOLLOW_LINKS=False`) — link extraction is handled by Crawl4AI.
- **User-Agent:** `Business-Scraper/1.0` (matches Crawl4AI for consistent server-side treatment).
- Returns same `PageResult` interface.

### 3.7 `page_processor.py` — Content Processing

- Strips residual nav/footer/cookie/ad elements via CSS selector blocklist
- Converts cleaned HTML to Markdown via `html2text` (`ignore_images=False`, `body_width=0`, `unicode_snob=True`)
- **Charset/encoding:** All HTML decoded as UTF-8. If `<meta charset>` tag specifies a different encoding, re-encode accordingly. Non-decodable bytes replaced with U+FFFD.
- **`page_type` auto-detection** — case-insensitive regex match on lowercase URL path. If multiple patterns match, priority order: `homepage > about > services > blog > case-study > contact > other`:

  | Pattern | `page_type` |
  |---|---|
  | `^/$` | `homepage` |
  | `/about`, `/team`, `/who-we-are`, `/our-story`, `/company` | `about` |
  | `/service`, `/solution`, `/what-we-do`, `/offering`, `/product` | `services` |
  | `/blog`, `/news`, `/insight`, `/article`, `/post`, `/update` | `blog` |
  | `/case-stud`, `/work`, `/portfolio`, `/project`, `/client` | `case-study` |
  | `/contact`, `/get-in-touch`, `/reach-us` | `contact` |
  | _(no match)_ | `other` |

- Injects rich YAML frontmatter:

```yaml
---
url: https://example.com/services/consulting
canonical_url: https://example.com/services/consulting
title: Consulting Services
description: We help companies transform digitally...
language: en
page_type: services
domain: example.com
scraped_at: 2026-03-17T10:23:45Z
word_count: 842
engine_used: crawl4ai
headings:
  - h1: Consulting Services
  - h2: What We Do
  - h2: Our Process
  - h2: Results
---
```

### 3.8 `exporter.py` — Output Builder

Produces the following output structure inside a `.zip`:

```
<domain>-<date>.zip
├── master_site.md              # All pages concatenated with --- separators
├── crawl_report.md             # Summary: counts, engines, failures, word totals
├── external_links.md           # External/social URLs grouped by domain
├── crawl.log                   # Full crawl log (all events)
└── individual_pages/
    ├── homepage.md
    ├── services-consulting.md
    ├── about-team.md
    └── ...
```

- Filenames are URL-slugified: `/services/consulting/` → `services-consulting.md`
- Pages in `master_site.md` ordered by `page_type` then URL for logical reading
- `crawl_report.md`: total scraped, skipped (with reason breakdown), failed, engine breakdown (crawl4ai vs scrapy), duplicate-content pages, total word count, crawl duration
- Pages requiring login are exported as `status: failed`, `skip_reason: requires authentication`

---

## 4. Error Handling

### Per-URL failure hierarchy

```
URL dequeued
  → robots.txt disallowed?       → skip ("robots disallowed")
  → noindex meta tag?            → skip ("noindex")
  → external/login-gated URL?    → saved to external_links, skipped
  → Crawl4AI attempt (30s timeout)
      → success + content?       → process
      → TimeoutError             → Scrapy fallback ("crawl4ai timeout")
      → HTTP 5xx                 → Scrapy fallback ("crawl4ai 5xx")
      → empty content            → Scrapy fallback ("crawl4ai empty")
      → other exception          → Scrapy fallback ("crawl4ai error")
          → success + content?   → process (logged: "scrapy fallback")
          → failure              → mark failed ("both engines failed")
```

### HTTP error handling

| Status | Action |
|---|---|
| 404, 403, 410 | Log and skip, no retry (terminal) |
| 5xx | Trigger Scrapy fallback |
| Redirect loop (>3) | Skip ("redirect loop") |
| Timeout | Crawl4AI: 30s → fallback; Scrapy: 20s → failed |
| Empty content | Trigger fallback; if fallback also empty → skip ("empty content") |
| Connection error | Log and continue ("connection error") |
| Requires auth (redirect to login page) | Skip ("requires authentication") |

### Crawl safety limits

- **Max pages:** User-configurable (default 500)
- **Max depth:** 10 levels from seed URL
- **Off-domain links:** Never queued
- **Content dedup:** Logged in `crawl_report.md`, not blocked from export

---

## 5. Streamlit UI

### Layout

```
┌─────────────────────────────────────────────┐
│  Business Scraper                           │
├─────────────────────────────────────────────┤
│  Target URL: [________________________] [Start] │
│  Max pages [500]   Rate limit [1.0s]         │
├─────────────────────────────────────────────┤
│  STATS BAR (updates on each page result)    │
│  Pages found: 42 | Scraped: 31 | Failed: 1  │
│  Crawl4AI: 28  | Scrapy fallback: 3         │
│  Words collected: 48,203                    │
├─────────────────────────────────────────────┤
│  LIVE FEED (scrolling log, last 50 lines)   │
│  [OK]   /services/consulting [crawl4ai] 842w    │
│  [OK]   /about/team [crawl4ai] 312w             │
│  [WARN] /blog/post-1 [scrapy fallback] 1,204w   │
│  [SKIP] /careers/apply  noindex                 │
│  [FAIL] /old-page  both engines failed          │
├─────────────────────────────────────────────┤
│  [Download .zip]  (appears when done)       │
└─────────────────────────────────────────────┘
```

### Async / Streamlit model

Streamlit does not support true background tasks — every UI interaction triggers a full script rerun. The crawl is driven by a **generator-based streaming pattern**:

1. On `[Start]`, `st.session_state.crawl_gen` is set to the `hybrid_scraper.crawl()` async generator.
2. App enters a **controlled loop**: each iteration calls `next()` on the generator (via `asyncio.run`), gets one `PageResult`, updates `st.session_state` stats and log.
3. After each result, `st.rerun()` triggers a Streamlit rerun — the loop continues from `session_state`.
4. Loop exits when generator is exhausted (crawl complete) or `st.session_state.cancel` is set.
5. `[Cancel]` sets `session_state.cancel = True`; the generator checks this flag at the top of each iteration and raises `StopAsyncIteration` gracefully — queue state is preserved in Redis.

**Log storage:** Live feed lines stored in `st.session_state.log_lines` (last 50). Full log also written to Redis `{domain}:log` (last 500 lines) and flushed to `crawl.log` on completion.

**Log format:** ASCII symbols for cross-platform compatibility: `[OK]`, `[WARN]`, `[SKIP]`, `[FAIL]`.

### Resume behaviour

If the same domain is entered and Redis has existing state:
> *"Existing crawl found: 31/42 pages done. Resume or start fresh?"*

"Start fresh" flushes all Redis keys for that domain before re-seeding.

### Graceful shutdown (SIGTERM in Docker)

On container SIGTERM:
1. `session_state.cancel` flag is set
2. Current page scrape completes (up to 30s)
3. Redis state is flushed/persisted
4. Browser (Playwright) is closed cleanly
5. Container exits within 10s of SIGTERM

---

## 6. Docker & Deployment

### `docker-compose.yml`

```yaml
services:
  app:
    build: .
    ports: ["8501:8501"]
    volumes:
      - ./output:/app/output
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on: [redis]
    stop_grace_period: 15s

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --save 60 1

volumes:
  redis_data:
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

# Install Chromium system dependencies
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Use python -m playwright to ensure the correct package is invoked
RUN python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8501
ENTRYPOINT ["streamlit", "run", "app.py", "--server.address", "0.0.0.0"]
```

### Running locally

```bash
docker compose up --build
# Open http://localhost:8501
```

### Cloud path (future)

No code changes required — only `docker-compose.yml` environment changes:
- Replace Redis container with managed Redis (AWS ElastiCache, Upstash, Redis Cloud)
- Add S3/GCS volume for `./output`
- Add reverse proxy (nginx/Caddy) for HTTPS

---

## 7. Key Dependencies

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | latest | UI framework |
| `crawl4ai` | >=0.3.5 | Primary scraper (Playwright-based, LLM-optimised) |
| `scrapy` | latest | Fallback scraper framework |
| `scrapy-playwright` | latest | Playwright integration for Scrapy |
| `playwright` | latest | Headless browser (shared by both engines) |
| `redis` | latest | Crawl queue and state persistence |
| `beautifulsoup4` | latest | HTML parsing (Scrapy fallback path) |
| `html2text` | latest | HTML to Markdown conversion |
| `pyyaml` | latest | YAML frontmatter generation |
| `robotparser` | stdlib | robots.txt parsing |
| `hashlib` | stdlib | Content deduplication |

---

## 8. Out of Scope (for now)

- Login-protected pages (pages requiring authentication are skipped with `skip_reason: requires authentication`)
- Multi-domain crawls (single target domain per session)
- Scheduled/automated crawls (manual trigger only)
- PDF/image content extraction
- Full visual site map in the UI
- Parallel scraping (single-threaded by design for rate limiting and memory safety)
