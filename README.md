# CIS

Company Intelligence Scraper is a lightweight scrape-first workspace for collecting public company website data, saving a clean JSON corpus, exporting a business-focused Excel workbook, and optionally building a local RAG experience on top of completed scrape jobs.

## Why CIS Exists

CIS exists for a simple local workflow:

1. scrape a public company website
2. keep canonical JSON artifacts
3. export something immediately useful

The primary value is reliable scrape and export. Indexing and chat are optional post-scrape layers, not required runtime complexity during the crawl itself.

## What It Does

- discovers a company site from `llm.txt`, `robots.txt`, sitemaps, and internal links
- crawls the site with a simple two-engine path:
  - static HTML extraction
  - browser extraction via Crawl4AI when needed
- saves canonical page records as JSON
- cleans and classifies pages into business-relevant groups
- exports:
  - job ZIP bundle
  - clean corpus JSONL
  - extracted entities JSON
  - Excel workbook with:
    - `Summary`
    - `Services`
    - `Case Studies`
    - `Partners`
    - `Customers`
    - `People`
    - `Events`
    - `Page Inventory`
- optionally builds a Qdrant search index from completed scrape jobs
- optionally runs local RAG chat with bundled Ollama

## Quick Start

### Recommended: Docker

```bash
docker compose up --build
```

Then open `http://localhost:8501`.

The default stack starts:

- the Streamlit app
- `ollama`
- `qdrant`
- a one-time Ollama bootstrap step that pulls:
  - `qwen3:4b-instruct`
  - `nomic-embed-text`

Notes:

- first startup can take a while because the Ollama models need to download
- scrape and export are the primary path
- Index and Chat are available after the services are up

### Local Python

Use Python `3.11+`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
streamlit run app.py
```

For local Python runs:

- scrape and export work without indexing
- Index and Chat require a reachable Ollama and Qdrant, or alternate provider settings in the app
- `.env.example` uses host-local defaults; Docker Compose injects service URLs automatically inside containers

## Typical Workflow

1. `Scrape`
   - enter a company URL
   - run a crawl job
   - wait for the job to finish writing JSON artifacts and export files
2. `Jobs`
   - inspect the completed job
   - download `intel.xlsx`, `entities.json`, `corpus.jsonl`, or the ZIP bundle
   - resume interrupted jobs
3. optional `Index`
   - build a vector index from a completed scrape job
4. optional `Chat`
   - ask grounded questions against the indexed corpus and extracted entities

Example:

1. scrape `https://example.com`
2. open `Jobs` and download `intel.xlsx`
3. review the exported services, customers, people, and events
4. if needed, build an index and ask follow-up questions in `Chat`

## Storage Model

Each completed job is written under `data/jobs/<job_id>/` and includes:

- `job.json`
- `crawl.log.jsonl`
- `pages/raw/*.json`
- `pages/clean/*.json`
- `exports/intel.xlsx`
- `exports/entities.json`
- `exports/corpus.jsonl`

JSON is the source of truth. Standalone Markdown page files are not persisted.

## Configuration

Environment variables can override runtime defaults. See [.env.example](.env.example).

Common settings:

- `OLLAMA_URL`
- `QDRANT_URL`
- `APP_TIMEZONE`
- `APP_DEFAULT_LLM_BACKEND`
- `APP_DEFAULT_EMBEDDING_BACKEND`
- `APP_DEFAULT_OLLAMA_LLM_MODEL`
- `APP_DEFAULT_OLLAMA_EMBEDDING_MODEL`

## Known Limitations

- CIS is built for public company websites, not authenticated apps, paywalled content, or aggressive anti-bot surfaces.
- The crawler is first-party and scrape-first by design. External enrichment is limited and not the primary workflow.
- Page classification and entity extraction are heuristic. Review exported results before treating them as complete ground truth.
- Some JavaScript-heavy pages may still fail or fall back to static extraction.
- Index and Chat are optional. They depend on a reachable Ollama and Qdrant setup, or alternate provider configuration.
- JSON artifacts are canonical. Standalone Markdown page files are intentionally not persisted.

## Open Source Notes

- This project is intended for public company websites and publicly available content.
- `benchmarks/` is optional internal QA tooling for extractor tuning. It is not required for normal scraping.
- Local runtime files under `data/` are ignored by git.
- Docker and app defaults are chosen for a self-contained local workflow first.

## Development

```bash
python -m compileall app.py app_settings.py chat company_intel indexer pages scraper tests
pytest -q
```

Focused test runs are often faster while iterating on a specific area:

```bash
pytest -q tests/test_chat_page_helpers.py tests/test_generator.py
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
