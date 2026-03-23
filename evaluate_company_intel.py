from __future__ import annotations

import argparse
from pathlib import Path

from company_intel.evaluation import BenchmarkCase, evaluate_job, write_report
from company_intel.storage import JobStorage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a completed company-intel job against a benchmark file.",
    )
    parser.add_argument("--job-id", required=True, help="Completed crawl job id under data/jobs/")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark JSON file")
    parser.add_argument("--jobs-dir", default="data/jobs", help="Base jobs directory")
    parser.add_argument(
        "--out-dir",
        default="",
        help="Optional output directory for benchmark reports. Defaults to the job export directory.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    storage = JobStorage(base_dir=Path(args.jobs_dir))
    benchmark = BenchmarkCase.load(Path(args.benchmark))
    report = evaluate_job(args.job_id, benchmark, storage=storage)

    output_dir = Path(args.out_dir) if args.out_dir else storage.job_dir(args.job_id) / "exports" / "evaluation"
    json_path, markdown_path = write_report(report, output_dir)
    overall = report.overall()

    print(f"Benchmark: {report.benchmark_name}")
    print(f"Job ID: {report.job_id}")
    print(
        "Overall: "
        f"precision={overall['precision']:.4f} "
        f"recall={overall['recall']:.4f} "
        f"f1={overall['f1']:.4f}"
    )
    print(f"Wrote: {json_path}")
    print(f"Wrote: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
