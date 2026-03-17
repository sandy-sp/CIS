# RAG Product Roadmap — 4-Step Pipeline

> **Synthesized from:** Gemini architecture research + Codex codebase audit (2026-03-17)

---

## Current State (Step 1 — ~70% Complete)

**What works well:**
- Streamlit UI with live stats, download .zip
- Redis-backed BFS queue with URL + content-hash dedup
- Crawl4AI (Playwright headless) as primary engine
- Scrapy fallback for failed pages + robots-disallowed pages
- Sitemap parsing from robots.txt Sitemap: directive (just added)
- YAML frontmatter with url, title, page_type, word_count, scraped_at
- Docker-compose with Redis healthcheck + SSL certs fixed

**Step 1 Gaps (ranked by impact):**
1. **Pagination / infinite scroll** — "Load More" buttons and page=2 URLs not discovered
2. **JavaScript-rendered links** — links injected by React/Next.js after hydration missed by link extractor
3. **No auth support** — login walls / paywalls block ~15% of business sites
4. **No retry with backoff** — transient failures mark URL as permanently failed
5. **URL fragment explosion** — `page.html#section1` vs `page.html#section2` treated as separate URLs
6. **No progress persistence to disk** — if Docker crashes mid-crawl, all session_state is lost
7. **Rate limit not per-domain** — all requests throttled globally, not per-domain (matters for sitemaps)
8. **Scrapy subprocess overhead** — spawning a new process per URL is slow for large sites
9. **No page content validation** — login redirect pages (200 OK but contains "Sign in") counted as success
10. **Terms of Service / Privacy Policy noise** — 5000+ word legal pages bloat the RAG context

---

## Step 2 — Data Cleaning (NEW MODULE: `processor/`)

**Gemini recommendation: Trafilatura + MinHash**

### What needs to be built:
```
processor/
├── cleaner.py          # Trafilatura-based HTML → clean Markdown
├── chunker.py          # Recursive character splitting (800-1000 chars, 10-15% overlap)
├── deduplicator.py     # MinHash (datasketch) for near-duplicate detection
└── pipeline.py         # Orchestrates: clean → dedup → chunk → save
```

### Key decisions:
- **Library:** `trafilatura>=1.12` (beats readability, newspaper3k in benchmarks)
- **Clean BEFORE chunk** — cleaning at the HTML level is more reliable than post-Markdown
- **Chunk strategy:** Section headings (`##`) as primary split, then recursive char split at 800 chars
- **Near-dedup:** MinHash with Jaccard threshold 0.85 to catch same page with different URLs
- **Discard threshold:** < 50 words after cleaning (keeps contact addresses, discards empty nav pages)
- **High-noise URL patterns to skip:** `/privacy`, `/terms`, `/cookie`, `/legal`, `/sitemap`

### Metadata per chunk (stored in YAML frontmatter):
```yaml
url: https://example.com/services
title: Our Services
page_type: services
chunk_index: 2
chunk_total: 5
section_heading: "Cloud Solutions"
word_count: 187
cleaned_at: 2026-03-17T...
```

### Streamlit UI — Step 2 Tab:
- Show table: original word count → cleaned word count → chunks created
- "High noise" pages flagged for review before chunking
- Download clean chunks as .zip

---

## Step 3 — Vector Database (NEW MODULE: `indexer/`)

**Gemini recommendation: Qdrant + BGE-M3**

### What needs to be built:
```
indexer/
├── embedder.py         # BGE-M3 (local) or OpenAI/Voyage API
├── vector_store.py     # Qdrant client wrapper (upsert, search, delete)
└── pipeline.py         # Orchestrates: load chunks → embed → upsert to Qdrant
```

### Key decisions:
- **Vector DB:** `qdrant-client` + Qdrant in Docker (Rust, fast, hybrid search)
  - Add to docker-compose.yml: `qdrant/qdrant:latest` on port 6333
- **Embedding model (local):** `BAAI/bge-m3` via `sentence-transformers>=3.0`
  - Supports dense + sparse + multi-vector in one model
  - ~570MB download, runs on CPU (slow) or GPU (fast)
- **Embedding model (API):** OpenAI `text-embedding-3-small` or Voyage AI `voyage-3`
- **Chunking:** 800-1000 chars, 10-15% overlap (from Step 2)
- **Metadata stored in Qdrant payload:** url, title, page_type, chunk_index, section_heading

### docker-compose.yml additions:
```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports:
    - "6333:6333"
  volumes:
    - qdrant_storage:/qdrant/storage
```

### Streamlit UI — Step 3 Tab:
- Choose: Local (BGE-M3 via sentence-transformers) OR API (OpenAI/Voyage key input)
- Progress bar: X/Y chunks embedded
- Show collection stats: total vectors, dimensions, collection size

---

## Step 4 — Chat Interface (NEW MODULE: `chat/`)

**Gemini recommendation: Two-stage retrieval + Llama 3.1 8B via Ollama**

### What needs to be built:
```
chat/
├── retriever.py        # Qdrant hybrid search + BGE Reranker v2
├── generator.py        # Ollama or OpenAI/Anthropic API chat
└── app_chat.py         # Streamlit chat UI (st.chat_message + citations)
```

### Key decisions:
- **Retrieval:** Two-stage
  1. Phase 1: Pull top 50 candidates via Qdrant hybrid search (BM25 + vector)
  2. Phase 2: Rerank to top 5 with `BAAI/bge-reranker-v2-m3` (local) or Jina Reranker v3
- **Local LLM:** Llama 3.1 8B via Ollama (best quality/speed tradeoff for RAG in 2025)
- **API LLMs:** OpenAI GPT-4o-mini, Anthropic claude-haiku-4-5 (cheapest capable models)
- **RAG prompt:**
  ```
  You are a business intelligence assistant. Answer questions using ONLY the provided context.
  If the answer is not in the context, say "I don't know based on the scraped content."
  Cite sources as [Page Title](URL) after each claim.
  Context: {context}
  Question: {question}
  ```
- **Multi-turn:** Keep last 5 turns in session_state, include in prompt
- **Citations:** `st.expander("Sources")` showing chunk text + link per answer

---

## Architecture — Full Product

```
business-rag/
├── scraper/          # Step 1 (EXISTS — needs ~4 more improvements)
├── processor/        # Step 2 (NEW)
├── indexer/          # Step 3 (NEW)
├── chat/             # Step 4 (NEW)
├── data/
│   ├── raw/          # ZIP from Step 1 (individual Markdown files)
│   ├── clean/        # Cleaned + chunked Markdown from Step 2
│   └── pipeline.db   # SQLite: tracks URL status across all 4 steps
├── app.py            # Multi-page Streamlit: Scrape | Clean | Index | Chat
├── docker-compose.yml  # app + redis + qdrant
└── requirements.txt
```

### State management:
- **Redis** — Step 1 crawl queue only (existing)
- **SQLite** (`data/pipeline.db`) — tracks per-URL status across all 4 steps
  - Table: `pages(url, scraped_at, cleaned_at, indexed_at, page_type, word_count, chunk_count)`
- **Filesystem** — `data/raw/` and `data/clean/` as source of truth

### Multi-page Streamlit:
```python
pages = {
    "🕷️ Scrape":  scrape_page,    # existing app.py logic
    "🧹 Clean":   clean_page,     # Step 2
    "🗄️ Index":   index_page,     # Step 3
    "💬 Chat":    chat_page,      # Step 4
}
```

---

## Implementation Phases

### Phase 1 — Finish Step 1 (1-2 sessions)
Priority fixes from Codex audit:
- [ ] Fix URL fragment dedup (strip #fragment before enqueue)
- [ ] Add retry with exponential backoff (3 attempts, 2/4/8s)
- [ ] Add login-redirect detection ("Sign in" / "Log in" in title → mark failed)
- [ ] Add high-noise URL pattern skip list (/privacy, /terms, /legal)
- [ ] Persist crawl progress to SQLite (not just Redis) for crash recovery

### Phase 2 — Build Step 2 (2-3 sessions)
- [ ] `processor/cleaner.py` — Trafilatura cleaning
- [ ] `processor/chunker.py` — recursive char split + section-heading split
- [ ] `processor/deduplicator.py` — MinHash near-dedup
- [ ] Step 2 Streamlit tab
- [ ] SQLite pipeline tracking

### Phase 3 — Build Step 3 (2-3 sessions)
- [ ] Add Qdrant to docker-compose.yml
- [ ] `indexer/embedder.py` — BGE-M3 local + API fallback
- [ ] `indexer/vector_store.py` — Qdrant wrapper
- [ ] Step 3 Streamlit tab with embedding progress

### Phase 4 — Build Step 4 (2-3 sessions)
- [ ] `chat/retriever.py` — Qdrant hybrid + BGE Reranker
- [ ] `chat/generator.py` — Ollama + OpenAI/Anthropic
- [ ] Step 4 Streamlit chat UI with citations
- [ ] Settings page: API keys, model selection, Ollama endpoint

---

## New Dependencies to Add

```
# Step 2
trafilatura>=1.12.0
datasketch>=1.6.5

# Step 3
qdrant-client>=1.9.0
sentence-transformers>=3.0.0
FlagEmbedding>=1.2.0      # BGE-M3

# Step 4
ollama>=0.2.0
openai>=1.30.0
anthropic>=0.28.0
```

---

## Quick Wins (can do NOW)
1. Fix URL fragment dedup — 2 lines in `queue_manager.normalize()`
2. Add `/privacy|/terms|/legal|/cookie` skip pattern to `hybrid_scraper.py`
3. Add retry with backoff to `crawl4ai_engine.py` and `scrapy_engine.py`

---

## Codex Audit — Critical Bugs Found (must fix before Phase 2)

### BUG-A: Content dedup is silently broken
**File:** `scraper/hybrid_scraper.py:49` + `scraper/page_processor.py:31`
`PageProcessor.process()` prepends YAML frontmatter (containing `url` + `scraped_at`) to the markdown **before** `HybridScraper` hashes it. Two pages with identical body content but different URLs/timestamps hash differently → dedup never fires.
**Fix:** Hash `result.markdown` (the raw body) BEFORE calling `page_processor.process()`.

### BUG-B: Resume is not end-to-end — ZIP will be empty after restart
**File:** `app.py:80` + `app.py:126`
Successful pages only live in `st.session_state.results` (in-memory). `_build_zip()` reads only from that list. If Docker restarts mid-crawl or user resumes, the queue continues but the final ZIP contains only the current session's pages.
**Fix:** Persist each successful `PageResult` to Redis (as JSON) or disk immediately on scrape. On resume, reload from Redis before starting the thread.

### BUG-C: `has_existing_state()` always returns True after a completed crawl
**File:** `scraper/queue_manager.py:91`
Checks `enqueued` set which is never cleared after completion → every subsequent attempt shows "Resume" prompt even for finished crawls.
**Fix:** Also check that `queue` list length > 0, OR add a `completed` flag to meta.

### BUG-D: Scrapy Playwright never actually enables JS rendering
**File:** `scraper/scrapy_worker.py:35`
`parse()` receives a raw HTTP response — Playwright handlers are registered but no request ever sets `meta["playwright"] = True`, so JS-heavy pages are scraped without browser rendering.
**Fix:** Set `meta = {"playwright": True}` on the start request.

### Phase 0 — Critical Bug Fixes (BEFORE anything else)
- [ ] Fix BUG-A: hash before YAML injection in `hybrid_scraper.py`
- [ ] Fix BUG-B: persist PageResult to Redis on each success; reload on resume
- [ ] Fix BUG-C: fix `has_existing_state()` to check queue length + add `completed` meta flag
- [ ] Fix BUG-D: enable Playwright in scrapy_worker start request
- [ ] Fix URL fragment dedup: strip `#fragment` in `queue_manager.normalize()`
- [ ] Add retry/backoff: 3 attempts, 2/4/8s in `hybrid_scraper.py`
- [ ] Add high-noise URL skip: `/privacy|/terms|/legal|/cookie|/sitemap` pattern

