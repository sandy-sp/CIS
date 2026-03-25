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

## Output

Each completed job is written under `data/jobs/<job_id>/` and includes:

- `job.json`
- `crawl.log.jsonl`
- `pages/raw/*.json`
- `pages/clean/*.json`
- `pages/markdown/*.md`
- `exports/intel.xlsx`
- `exports/entities.json`
- `exports/corpus.jsonl`

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

The scrape/export path is designed to work without vector DB or chat services.

```bash
docker compose up --build
```

The app will be available at `http://localhost:8501`.

## Notes

- `benchmarks/` is internal extractor QA tooling and is not part of the scrape workflow.
- RAG/index/chat are intentionally out of the active product path until scrape/export is stable again.
