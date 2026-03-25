from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from company_intel.storage import JobStorage


_ROOT_DIR = Path(__file__).resolve().parent.parent


def launch_worker(job_id: str, storage: JobStorage | None = None) -> int:
    storage = storage or JobStorage()
    worker_log = storage.job_dir(job_id) / "worker.log"
    with worker_log.open("ab") as log_handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "company_intel.worker", job_id],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(_ROOT_DIR),
            close_fds=True,
        )
    storage.save_worker_pid(job_id, proc.pid)
    return proc.pid
