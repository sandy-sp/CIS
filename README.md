# CIS

Company Intelligence Scraper is a lightweight scrape-first workspace for collecting public company website data, saving a clean JSON corpus, exporting a business-focused Excel workbook, and optionally building a local RAG experience on top of completed scrape jobs.

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

## Product Flow

1. `Scrape`
   - enter a company URL
   - preview discovery and page counts
   - run a crawl job
   - watch live scraped, skipped, denied, and failed counts
2. `Jobs`
   - inspect completed jobs
   - download the ZIP, Excel export, entity JSON, or corpus JSONL
   - resume interrupted jobs
3. `Settings`
   - use bundled Ollama defaults or override with your own provider settings
4. `Index`
   - build a vector index from a completed scrape job
5. `Chat`
   - ask grounded questions against the indexed corpus and extracted entities

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

## Quick Start

### Docker

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

### Local Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

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

## Open Source Notes

- This project is intended for public company websites and publicly available content.
- `benchmarks/` is optional internal QA tooling for extractor tuning. It is not required for normal scraping.
- Local runtime files under `data/` are ignored by git.
- Docker and app defaults are chosen for a self-contained local workflow first.

## Development

```bash
pytest -q
```

Focused test runs are often faster while iterating on a specific area:

```bash
pytest -q tests/test_chat_page_helpers.py tests/test_generator.py
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
