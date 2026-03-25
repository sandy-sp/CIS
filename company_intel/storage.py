from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from company_intel.models import CrawlJob, CrawlSettings, ExtractedEntity, PageRecord


_DEFAULT_BASE = Path("data/jobs")


def _slugify(value: str) -> str:
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value)
    value = value.strip("-").lower()
    return value or "site"


def _mirror_path(url: str) -> Path:
    parsed = urlparse(url)
    path = unquote(parsed.path or "/")
    parts = [re.sub(r"[^a-zA-Z0-9._-]+", "-", part).strip("-") or "index" for part in path.split("/") if part]
    if not parts:
        parts = ["index"]
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    if query:
        parts[-1] = f"{parts[-1]}__{_slugify(query)[:80]}"
    return Path(*parts)


def _write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding=encoding,
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)


def _read_json_with_retry(path: Path, *, retries: int = 5, delay: float = 0.05) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                raise json.JSONDecodeError("empty content", raw, 0)
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt >= retries - 1:
                raise
            time.sleep(delay)
    if last_error:
        raise last_error
    raise RuntimeError(f"Unable to read JSON from {path}")


class JobStorage:
    def __init__(self, base_dir: Path = _DEFAULT_BASE):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, settings: CrawlSettings) -> CrawlJob:
        parsed = urlparse(settings.start_url)
        domain = parsed.netloc.lstrip("www.")
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        job_id = f"{timestamp}-{_slugify(domain)}"
        job = CrawlJob(
            job_id=job_id,
            domain=domain,
            settings=settings,
            output_dir=str(self.job_dir(job_id)),
        )
        self.job_dir(job_id).mkdir(parents=True, exist_ok=True)
        self._ensure_dirs(job_id)
        self.save_job(job)
        return job

    def job_dir(self, job_id: str) -> Path:
        return self.base_dir / job_id

    def save_job(self, job: CrawlJob) -> None:
        job.touch()
        path = self.job_dir(job.job_id) / "job.json"
        _write_text_atomic(path, json.dumps(job.to_dict(), indent=2, sort_keys=True))

    def load_job(self, job_id: str) -> CrawlJob:
        path = self.job_dir(job_id) / "job.json"
        return CrawlJob.from_dict(_read_json_with_retry(path))

    def list_jobs(self, status: str | None = None) -> list[CrawlJob]:
        jobs: list[CrawlJob] = []
        for path in sorted(self.base_dir.glob("*/job.json"), reverse=True):
            try:
                job = CrawlJob.from_dict(_read_json_with_retry(path))
            except Exception:
                continue
            if status and job.status != status:
                continue
            jobs.append(job)
        return jobs

    def raw_page_path(self, job_id: str, url: str) -> Path:
        return self.job_dir(job_id) / "pages" / "raw" / _mirror_path(url).with_suffix(".json")

    def clean_page_path(self, job_id: str, url: str) -> Path:
        return self.job_dir(job_id) / "pages" / "clean" / _mirror_path(url).with_suffix(".json")

    def external_record_path(self, job_id: str, url: str) -> Path:
        domain = _slugify(urlparse(url).netloc.lstrip("www."))
        return self.job_dir(job_id) / "externals" / domain / _mirror_path(url).with_suffix(".json")

    def crawl_log_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "crawl.log.jsonl"

    def cancel_request_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "cancel.request"

    def worker_pid_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "worker.pid"

    def save_page_record(self, job_id: str, record: PageRecord) -> None:
        self._ensure_dirs(job_id)
        raw_path = self.raw_page_path(job_id, record.url)
        clean_path = self.clean_page_path(job_id, record.url)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.parent.mkdir(parents=True, exist_ok=True)

        raw_doc = {
            "url": record.url,
            "normalized_url": record.normalized_url,
            "domain": record.domain,
            "path": record.path,
            "source_type": record.source_type,
            "status": record.status,
            "status_code": record.status_code,
            "title": record.title,
            "description": record.description,
            "headings": record.headings,
            "language": record.language,
            "raw_html": record.raw_html,
            "raw_text": record.raw_text,
            "engine_selected": record.engine_selected,
            "engine_used": record.engine_used,
            "robots_disallowed": record.robots_disallowed,
            "llm_disallowed": record.llm_disallowed,
            "outbound_links": record.outbound_links,
            "metadata": record.metadata,
        }
        _write_text_atomic(raw_path, json.dumps(raw_doc, indent=2, sort_keys=True))
        record.source_file = str(clean_path.relative_to(self.job_dir(job_id)))
        _write_text_atomic(clean_path, json.dumps(record.to_dict(), indent=2, sort_keys=True))
        if record.source_type == "external":
            external_json = self.external_record_path(job_id, record.url)
            external_json.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(external_json, json.dumps(record.to_dict(), indent=2, sort_keys=True))

    def load_page_records(self, job_id: str, source_type: str | None = None) -> list[PageRecord]:
        records: list[PageRecord] = []
        clean_dir = self.job_dir(job_id) / "pages" / "clean"
        if not clean_dir.exists():
            return records
        for path in sorted(clean_dir.rglob("*.json")):
            try:
                record = PageRecord.from_dict(_read_json_with_retry(path))
            except Exception:
                continue
            if source_type and record.source_type != source_type:
                continue
            records.append(record)
        return records

    def append_crawl_log(self, job_id: str, entry: dict) -> None:
        path = self.crawl_log_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def load_crawl_log(self, job_id: str, limit: int = 50) -> list[dict]:
        path = self.crawl_log_path(job_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def request_cancel(self, job_id: str) -> None:
        self.cancel_request_path(job_id).write_text("cancelled\n", encoding="utf-8")

    def cancel_requested(self, job_id: str) -> bool:
        return self.cancel_request_path(job_id).exists()

    def clear_cancel_request(self, job_id: str) -> None:
        path = self.cancel_request_path(job_id)
        if path.exists():
            path.unlink()

    def save_worker_pid(self, job_id: str, pid: int) -> None:
        self.worker_pid_path(job_id).write_text(str(pid), encoding="utf-8")

    def load_worker_pid(self, job_id: str) -> int | None:
        path = self.worker_pid_path(job_id)
        if not path.exists():
            return None
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def worker_is_running(self, job_id: str) -> bool:
        pid = self.load_worker_pid(job_id)
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def clear_worker_pid(self, job_id: str) -> None:
        path = self.worker_pid_path(job_id)
        if path.exists():
            path.unlink()

    def write_corpus_jsonl(self, job_id: str, records: list[PageRecord]) -> Path:
        export_dir = self.job_dir(job_id) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output = export_dir / "corpus.jsonl"
        lines = [json.dumps(record.to_dict(), sort_keys=True) for record in records]
        _write_text_atomic(output, "\n".join(lines))
        return output

    def write_entities(self, job_id: str, entities: dict[str, list[ExtractedEntity]]) -> Path:
        export_dir = self.job_dir(job_id) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output = export_dir / "entities.json"
        payload = {
            key: [entity.to_dict() for entity in values]
            for key, values in entities.items()
        }
        _write_text_atomic(output, json.dumps(payload, indent=2, sort_keys=True))
        return output

    def load_entities(self, job_id: str) -> dict[str, list[ExtractedEntity]]:
        path = self.job_dir(job_id) / "exports" / "entities.json"
        if not path.exists():
            return {}
        payload = _read_json_with_retry(path)
        entities: dict[str, list[ExtractedEntity]] = {}
        for key, values in payload.items():
            if not isinstance(values, list):
                continue
            entities[key] = [
                ExtractedEntity(**value)
                for value in values
                if isinstance(value, dict)
            ]
        return entities

    def bundle_job(self, job_id: str) -> bytes:
        buf = io.BytesIO()
        root = self.job_dir(job_id)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(root.parent))
        return buf.getvalue()

    def _ensure_dirs(self, job_id: str) -> None:
        root = self.job_dir(job_id)
        for rel in (
            "pages/raw",
            "pages/clean",
            "externals",
            "exports",
        ):
            (root / rel).mkdir(parents=True, exist_ok=True)


def collection_name_for_job(job_id: str, domain: str, include_external: bool = True) -> str:
    suffix = "full" if include_external else "internal"
    slug = _slugify(f"{domain}-{job_id}-{suffix}")[:96]
    return f"company-intel-{slug}"
