# Benchmarks

Benchmark files let you score extracted company-intel entities against a small gold dataset.

Generate a draft benchmark from a completed job before you curate the final gold set:

```bash
python draft_company_benchmark.py \
  --job-id 20260319T120000Z-example-com \
  --out benchmarks/example-company.json
```

Run a benchmark against a completed job:

```bash
python evaluate_company_intel.py \
  --job-id 20260319T120000Z-example-com \
  --benchmark benchmarks/example-company.json
```

This writes:

- `benchmark_report.json`
- `benchmark_report.md`

into `data/jobs/<job_id>/exports/evaluation/` by default.

## Benchmark Format

```json
{
  "name": "Example Company Benchmark",
  "company_domain": "example.com",
  "notes": "Initial gold set for extractor regression checks.",
  "entities": {
    "services": [
      {
        "name": "Data Platform Services",
        "aliases": ["Data Platform"],
        "attribute_checks": {
          "summary": { "contains": "scientific data platform" }
        },
        "source_url_contains": ["/services/data-platform"]
      }
    ],
    "people": [
      {
        "name": "Christopher McClure",
        "attribute_checks": {
          "title": { "contains": "Director" },
          "linkedin_url": { "contains": "linkedin.com/in/" }
        }
      }
    ]
  }
}
```

## Supported Checks

- `equals`: case-insensitive exact string match after whitespace normalization
- `contains`: case-insensitive substring match after whitespace normalization
- `one_of`: case-insensitive exact match against one of several values

Supported entity keys should match the extractor output keys, for example:

- `company_profile`
- `services`
- `industries`
- `case_studies`
- `partners`
- `customers`
- `people`
- `events`
- `resources`
- `external_profiles`
