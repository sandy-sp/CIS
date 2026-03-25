from __future__ import annotations

import argparse
import os

from company_intel.job_runner import JobRunner
from company_intel.storage import JobStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a persisted scrape job worker.")
    parser.add_argument("job_id", help="Persisted crawl job identifier")
    args = parser.parse_args()

    storage = JobStorage()
    storage.save_worker_pid(args.job_id, os.getpid())
    runner = JobRunner(storage=storage)
    runner.run(args.job_id)


if __name__ == "__main__":
    main()
