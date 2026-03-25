# Contributing

Thanks for contributing to CIS.

## Development Setup

1. Create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt -r requirements-dev.txt`.
3. Run the app with `streamlit run app.py` or use `docker compose up --build`.

## Before Opening a PR

- keep changes focused
- add or update tests when behavior changes
- run `python -m compileall app.py app_settings.py chat company_intel indexer pages scraper tests`
- run `pytest -q`
- avoid committing local `data/` outputs, settings, or job artifacts

## Scope

The project is intentionally scrape-first.

Primary workflow:

- scrape a company site
- save JSON artifacts
- export Excel
- optionally build index and chat later

When adding features, prefer preserving scrape/export stability over adding more runtime complexity.
