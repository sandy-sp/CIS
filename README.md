# Company Intelligence Scraper

Internal scrape-first tool for collecting public first-party company website data, saving a clean JSON corpus, and exporting a structured Excel workbook.

## Current Workflow

1. `Scrape`
   - enter a company URL
   - preview site discovery from `llm.txt`, `robots.txt`, sitemap, and root
   - start a crawl job
   - watch discovered, scraped, skipped, and denied/failed counts
2. `Jobs`
   - inspect saved crawl jobs
   - download the full job ZIP
   - download the Excel export
   - download the saved corpus JSONL and extracted entities JSON
3. `Settings`
   - use bundled Ollama by default for chat and embeddings
   - optionally override with your own OpenAI or Anthropic keys
4. `Index`
   - build a Qdrant search index from a completed scrape job
   - embeddings are created from the saved JSON corpus fields, not standalone Markdown files
5. `Chat`
   - ask grounded questions against an indexed crawl corpus

## Output

Each completed job is written under `data/jobs/<job_id>/` and includes:

- `job.json`
- `crawl.log.jsonl`
- `pages/raw/*.json`
- `pages/clean/*.json`
- `exports/intel.xlsx`
- `exports/entities.json`
- `exports/corpus.jsonl`

Only JSON artifacts are persisted for page content. Markdown is not saved as separate `.md` files. If a scraper engine produces markdown-like text, it is kept only inside the JSON record as an intermediate field; the RAG index now prefers `clean_text` and `raw_text` from the saved JSON corpus.

## Excel Sheets

The Excel export focuses on the business deliverable:

- `Summary`
- `Services`
- `Case Studies`
- `Partners`
- `Customers`
- `People`
- `Events`
- `Page Inventory`

## Docker

The default Docker stack now starts:

- the Streamlit app
- `ollama` with `llama3.2:3b`
- `nomic-embed-text`
- `qdrant`

```bash
docker compose up --build
```

The app will be available at `http://localhost:8501`.

## Notes

- `benchmarks/` is internal extractor QA tooling and is not part of the scrape workflow.
- Scrape/export is still the primary workflow. RAG is a separate post-scrape phase built only from completed saved jobs.
