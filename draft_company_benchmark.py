from __future__ import annotations

import argparse
from pathlib import Path

from company_intel.evaluation import build_job_benchmark_draft
from company_intel.storage import JobStorage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a draft benchmark file from a completed company-intel job.",
    )
    parser.add_argument("--job-id", required=True, help="Completed crawl job id under data/jobs/")
    parser.add_argument("--jobs-dir", default="data/jobs", help="Base jobs directory")
    parser.add_argument("--out", required=True, help="Output benchmark JSON path")
    parser.add_argument("--limit-per-type", type=int, default=25, help="Maximum entries to include per entity type")
    parser.add_argument(
        "--entity-type",
        action="append",
        default=[],
        help="Optional entity type filter. Repeat for multiple types.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    storage = JobStorage(base_dir=Path(args.jobs_dir))
    benchmark = build_job_benchmark_draft(
        args.job_id,
        storage=storage,
        limit_per_type=max(args.limit_per_type, 1),
        entity_types=args.entity_type or None,
    )
    output = benchmark.save(Path(args.out))

    total_entries = sum(len(values) for values in benchmark.entities.values())
    print(f"Benchmark draft: {benchmark.name}")
    print(f"Entity types: {', '.join(sorted(benchmark.entities))}")
    print(f"Entries: {total_entries}")
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
