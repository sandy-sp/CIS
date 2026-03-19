from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_intel.models import PageRecord


_VALID_REVIEW_STATUSES = {"approved", "pending", "rejected"}


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _get_attr(record: PageRecord | dict[str, Any], name: str, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def external_review_status(record: PageRecord | dict[str, Any]) -> str:
    if _get_attr(record, "source_type") != "external":
        return "approved"
    metadata = _get_attr(record, "metadata", {}) or {}
    status = metadata.get("review_status", "")
    if status in _VALID_REVIEW_STATUSES:
        return status
    discovered_via = _get_attr(record, "discovered_via", "")
    return "approved" if discovered_via == "site-external-link" else "pending"


def set_external_review_status(record: PageRecord, status: str, review_source: str = "manual") -> PageRecord:
    if status not in _VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {status}")
    metadata = dict(record.metadata or {})
    metadata["review_status"] = status
    metadata["reviewed_at"] = _utcnow_iso()
    metadata["review_source"] = review_source
    record.metadata = metadata
    return record


def is_record_approved_for_outputs(record: PageRecord) -> bool:
    if record.source_type != "external":
        return True
    return external_review_status(record) == "approved"


def filter_records_for_outputs(records: list[PageRecord]) -> list[PageRecord]:
    return [record for record in records if is_record_approved_for_outputs(record)]
