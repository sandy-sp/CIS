# Business Scraper — Design Spec
**Date:** 2026-03-17
**Status:** Approved
**Purpose:** Dockerized web application that crawls a company website and converts all content into RAG-ready Markdown files for LLM consumption / vector DB ingestion.

---

## 1. Overview

Business Scraper takes a single company website URL, crawls its entire public domain (respecting ethical crawl rules), and produces clean, richly-annotated Markdown files optimized for RAG ingestion into a vector database.

**Primary use case:** Competitive intelligence and company due diligence — aggregate all public information from a company's website into structured, LLM-ready documents.

---

## 2. Architecture

```
business-scraper/
├── app.py                  # Streamlit UI + async orchestration
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
  → Snooper checks llm.txt / robots.txt / noindex policy
  → QueueManager seeds Redis with seed URLs
  → HybridScraper pulls URLs from queue in a loop
      → Crawl4AI attempts scrape (primary)
      → On failure → Scrapy fallback (thread pool)
  → PageProcessor converts result to Markdown + rich YAML frontmatter
  → Exporter writes individual pages + master_site.md
  → Streamlit shows live feed + stats panel
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
| `headings` | list[dict] | h1/h2 list: `[{h1: "..."}, {h2: "..."}]` |
| `raw_html` | str | Raw HTML before processing |
| `markdown` | str | Converted Markdown content |
| `page_type` | str | Auto-detected: about/services/blog/team/case-study/contact/other |
| `word_count` | int | Word count of extracted content |
| `scraped_at` | datetime | UTC timestamp |
| `engine_used` | str | `crawl4ai` or `scrapy` |
| `status` | str | `success` / `failed` / `skipped` |
| `skip_reason` | str | Reason if skipped/failed |

### 3.2 `snooper.py` — Pre-Crawl Intelligence

Runs once before crawl begins and once per page during crawl:

1. **`llm.txt` check** — GET `https://<domain>/llm.txt`. If found, parse URL list and use as seed queue directly (skip recursive crawl).
2. **`robots.txt` check** — Parse disallowed paths and `Crawl-delay`. Honour all directives. Store parsed rules for per-URL checks.
3. **Per-page noindex/nofollow** — Check `<meta name="robots" content="...">` on each fetched page:
   - `noindex` → skip page content, do not export
   - `nofollow` → do not follow outbound links from this page
4. **External URL detection** — URLs pointing off-domain (especially social platforms: LinkedIn, Instagram, Twitter/X, Facebook, YouTube) are captured and routed to `external_links.md` rather than queued for crawl.

### 3.3 `queue_manager.py` — Crawl State via Redis

Redis data structures:

| Key | Type | Purpose |
|---|---|---|
| `{domain}:queue` | List | Pending URLs (LPUSH/RPOP) |
| `{domain}:visited` | Set | URL-normalised visited set (dedup) |
| `{domain}:content_hashes` | Set | SHA-256 of page content (duplicate content detection) |
| `{domain}:failed` | Set | URLs both engines failed on |
| `{domain}:external_links` | Set | External/social URLs discovered |
| `{domain}:meta` | Hash | Crawl metadata: start_time, pages_done, pages_found |

**Resumability:** Crawl state survives container restarts. Re-entering the same domain resumes from where it left off. Already-visited URLs are never re-queued.

**Rate limiting:** Configurable delay between requests (default 1.0s). Respects `robots.txt` `Crawl-delay` when present. Delay applied per domain via Redis-based token bucket.

### 3.4 `hybrid_scraper.py` — Engine Orchestration

```
for each URL dequeued:
    if robots.txt disallows → skip
    if noindex meta tag     → skip
    if external/social URL  → save to external_links, skip

    try Crawl4AI:
        result = await crawl4ai_engine.scrape(url)
        if result.status == success AND content not empty:
            return result

    fallback to Scrapy (thread pool):
        result = scrapy_engine.scrape(url)   # blocking, in ThreadPoolExecutor
        if result.status == success AND content not empty:
            result.engine_used = "scrapy"
            return result

    mark as failed, log skip_reason = "both engines failed"
```

### 3.5 `crawl4ai_engine.py` — Primary Engine

- Uses `AsyncWebCrawler` from Crawl4AI
- Playwright-powered (handles JS-heavy pages natively)
- `CacheMode.DISABLED` (always fresh)
- `word_count_threshold=50` (skip near-empty pages)
- Content filter: `PruningContentFilter` to strip nav/footer/ads
- Markdown strategy: `DefaultMarkdownGenerator` with `fit_markdown=True`
- Timeout: 30 seconds per URL
- Extracts all on-domain links from each page and adds to queue

### 3.6 `scrapy_engine.py` — Fallback Engine

- Runs a single-URL `scrapy.Spider` via `CrawlerRunner` inside a `ThreadPoolExecutor`
- Uses `scrapy-playwright` for JS rendering on fallback pages
- Extracts content with `BeautifulSoup` + `html2text` for Markdown conversion
- Timeout: 20 seconds per URL
- Does **not** follow links (link extraction is handled by hybrid_scraper from Crawl4AI pass)
- Returns same `PageResult` interface

### 3.7 `page_processor.py` — Content Processing

- Strips residual nav/footer/cookie/ad elements via CSS selector blocklist
- Converts cleaned HTML to Markdown via `html2text` (configured: ignore images=False, body_width=0)
- **Auto-detects `page_type`** from URL path segments + h1 keyword matching:
  - `/about*`, `/team*`, `/who-we-are*` → `about`
  - `/service*`, `/solution*`, `/what-we-do*` → `services`
  - `/blog*`, `/news*`, `/insight*`, `/article*` → `blog`
  - `/case-stud*`, `/work*`, `/portfolio*`, `/project*` → `case-study`
  - `/contact*` → `contact`
  - Root `/` → `homepage`
  - Everything else → `other`
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
├── external_links.md           # Categorised external/social URLs found
└── individual_pages/
    ├── homepage.md
    ├── services-consulting.md
    ├── about-team.md
    └── ...
```

- Filenames are URL-slugified: `/services/consulting/` → `services-consulting.md`
- Pages in `master_site.md` are ordered by `page_type` then URL for logical reading order
- `crawl_report.md` includes: total pages scraped, skipped (with reasons), failed, engine breakdown, total word count, crawl duration

---

## 4. Error Handling

### Per-URL failure hierarchy

```
URL dequeued
  → robots.txt disallowed?       → skip (logged: "robots disallowed")
  → noindex meta tag?            → skip (logged: "noindex")
  → external/login-gated URL?    → saved to external_links.md, skipped
  → Crawl4AI attempt
      → success + content?       → process
      → timeout/error/empty      → Scrapy fallback
          → success + content?   → process (logged: "scrapy fallback")
          → failure              → mark failed (logged: "both engines failed")
```

### HTTP error handling

| Status | Action |
|---|---|
| 404, 403, 410 | Log and skip, no retry |
| 5xx | Retry once after 5s, then skip |
| Redirect loop (>3) | Skip |
| Timeout | Crawl4AI: 30s, Scrapy: 20s, then fallback/skip |
| Empty content | Skip (logged: "empty content") |
| Connection error | Log and continue |

### Crawl safety limits

- **Max pages:** User-configurable (default 500) — prevents runaway crawls
- **Max depth:** 10 levels from seed URL
- **Off-domain links:** Strictly never queued
- **Duplicate content:** SHA-256 hash checked; duplicate URLs logged but not re-exported

---

## 5. Streamlit UI

### Layout

```
┌─────────────────────────────────────────────┐
│  Business Scraper                           │
├─────────────────────────────────────────────┤
│  Target URL: [________________________] [Start] │
│  Options: Max pages [500]  Rate limit [1.0s] │
├─────────────────────────────────────────────┤
│  STATS BAR (live updates every 0.5s)        │
│  Pages found: 42 | Scraped: 31 | Failed: 1  │
│  Crawl4AI: 28  | Scrapy fallback: 3         │
│  Words collected: 48,203                    │
├─────────────────────────────────────────────┤
│  LIVE FEED (scrolling log, last 50 lines)   │
│  ✓ /services/consulting [crawl4ai] 842w     │
│  ✓ /about/team [crawl4ai] 312w              │
│  ⚠ /blog/post-1 [scrapy fallback] 1,204w   │
│  ✗ /careers/apply [skipped: noindex]        │
│  → /case-studies/acme [queued...]           │
├─────────────────────────────────────────────┤
│  [Download .zip]  (appears when done)       │
└─────────────────────────────────────────────┘
```

### Async model

- Crawl runs in a background `asyncio` task via `asyncio.create_task()`
- Streamlit uses `st.empty()` containers refreshed every 0.5s via polling loop
- No page reloads; UI stays responsive throughout
- `[Start]` button becomes `[Cancel]` during crawl
- On cancel: graceful shutdown — current page finishes, queue state preserved in Redis

### Resume behaviour

If the same domain is entered and Redis has existing state:
> *"Existing crawl found: 31/42 pages done. Resume or start fresh?"*

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

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --save 60 1

volumes:
  redis_data:
```

### `Dockerfile`

```
Base: python:3.11-slim
→ Install Chromium system dependencies
→ pip install -r requirements.txt
→ playwright install chromium --with-deps
→ EXPOSE 8501
→ ENTRYPOINT: streamlit run app.py --server.address 0.0.0.0
```

### Running locally

```bash
docker compose up --build
# Open http://localhost:8501
```

### Cloud path (future)

No code changes required. Only `docker-compose.yml` changes:
- Replace Redis container with managed Redis (AWS ElastiCache, Upstash, Redis Cloud)
- Add S3/GCS volume mount for `./output`
- Add reverse proxy (nginx/Caddy) for HTTPS

---

## 7. Key Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | UI framework |
| `crawl4ai` | Primary scraper (Playwright-based, LLM-optimised) |
| `scrapy` | Fallback scraper framework |
| `scrapy-playwright` | Playwright integration for Scrapy |
| `playwright` | Headless browser |
| `redis` | Crawl queue and state persistence |
| `beautifulsoup4` | HTML parsing (Scrapy fallback path) |
| `html2text` | HTML to Markdown conversion |
| `pyyaml` | YAML frontmatter generation |
| `robotparser` (stdlib) | robots.txt parsing |
| `hashlib` (stdlib) | Content deduplication |

---

## 8. Out of Scope (for now)

- Login-protected pages (public pages only)
- Multi-domain crawls (single target domain per session)
- Scheduled/automated crawls (manual trigger only)
- PDF/image content extraction
- Full visual site map in the UI
