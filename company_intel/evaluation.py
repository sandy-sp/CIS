from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from company_intel.models import ExtractedEntity
from company_intel.storage import JobStorage


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    compact = " ".join(str(value or "").strip().split())
    return compact.casefold()


def _normalize_key(value: str) -> str:
    chars = []
    for char in _normalize_text(value):
        chars.append(char if char.isalnum() else "-")
    return "".join(chars).strip("-")


def _safe_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(value, 4)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return _safe_float(numerator / denominator)


@dataclass
class BenchmarkEntity:
    name: str
    aliases: list[str] = field(default_factory=list)
    attribute_checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_url_contains: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkEntity":
        return cls(
            name=str(data.get("name", "") or ""),
            aliases=[str(value) for value in data.get("aliases", []) if str(value or "").strip()],
            attribute_checks={
                str(key): value
                for key, value in (data.get("attribute_checks", {}) or {}).items()
                if isinstance(value, dict)
            },
            source_url_contains=[
                str(value)
                for value in data.get("source_url_contains", [])
                if str(value or "").strip()
            ],
            notes=str(data.get("notes", "") or ""),
        )

    def name_keys(self) -> set[str]:
        values = [self.name] + self.aliases
        return {_normalize_key(value) for value in values if value.strip()}


@dataclass
class BenchmarkCase:
    name: str
    company_domain: str = ""
    notes: str = ""
    entities: dict[str, list[BenchmarkEntity]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCase":
        raw_entities = data.get("entities", {}) or {}
        entities: dict[str, list[BenchmarkEntity]] = {}
        for entity_type, values in raw_entities.items():
            if not isinstance(values, list):
                continue
            parsed = [
                BenchmarkEntity.from_dict(value)
                for value in values
                if isinstance(value, dict) and str(value.get("name", "") or "").strip()
            ]
            entities[str(entity_type)] = parsed
        return cls(
            name=str(data.get("name", "") or "benchmark"),
            company_domain=str(data.get("company_domain", "") or ""),
            notes=str(data.get("notes", "") or ""),
            entities=entities,
        )

    @classmethod
    def load(cls, path: Path) -> "BenchmarkCase":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "company_domain": self.company_domain,
            "notes": self.notes,
            "entities": {
                entity_type: [asdict(entity) for entity in entities]
                for entity_type, entities in self.entities.items()
            },
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return path


@dataclass
class EntityMatchResult:
    expected_name: str
    predicted_name: str = ""
    matched: bool = False
    failed_checks: list[str] = field(default_factory=list)
    passed_check_count: int = 0
    total_check_count: int = 0
    source_url_passed: int = 0
    source_url_total: int = 0
    expected_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityTypeReport:
    entity_type: str
    gold_count: int = 0
    predicted_count: int = 0
    matched_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    attribute_checks_passed: int = 0
    attribute_checks_total: int = 0
    source_url_checks_passed: int = 0
    source_url_checks_total: int = 0
    matches: list[EntityMatchResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    @property
    def attribute_accuracy(self) -> float:
        return _ratio(self.attribute_checks_passed, self.attribute_checks_total)

    @property
    def source_url_accuracy(self) -> float:
        return _ratio(self.source_url_checks_passed, self.source_url_checks_total)

    def finalize(self) -> None:
        self.precision = _ratio(self.matched_count, self.predicted_count)
        self.recall = _ratio(self.matched_count, self.gold_count)
        if self.precision + self.recall > 0:
            self.f1 = _safe_float((2 * self.precision * self.recall) / (self.precision + self.recall))
        else:
            self.f1 = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "gold_count": self.gold_count,
            "predicted_count": self.predicted_count,
            "matched_count": self.matched_count,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "attribute_checks_passed": self.attribute_checks_passed,
            "attribute_checks_total": self.attribute_checks_total,
            "attribute_accuracy": self.attribute_accuracy,
            "source_url_checks_passed": self.source_url_checks_passed,
            "source_url_checks_total": self.source_url_checks_total,
            "source_url_accuracy": self.source_url_accuracy,
            "matches": [match.to_dict() for match in self.matches],
            "missing": self.missing,
            "unexpected": self.unexpected,
        }


@dataclass
class EvaluationReport:
    benchmark_name: str
    company_domain: str
    evaluated_at: str
    job_id: str = ""
    notes: str = ""
    entity_types: dict[str, EntityTypeReport] = field(default_factory=dict)

    def overall(self) -> dict[str, Any]:
        gold_count = sum(report.gold_count for report in self.entity_types.values())
        predicted_count = sum(report.predicted_count for report in self.entity_types.values())
        matched_count = sum(report.matched_count for report in self.entity_types.values())
        attribute_passed = sum(report.attribute_checks_passed for report in self.entity_types.values())
        attribute_total = sum(report.attribute_checks_total for report in self.entity_types.values())
        source_passed = sum(report.source_url_checks_passed for report in self.entity_types.values())
        source_total = sum(report.source_url_checks_total for report in self.entity_types.values())
        precision = _ratio(matched_count, predicted_count)
        recall = _ratio(matched_count, gold_count)
        f1 = 0.0
        if precision + recall > 0:
            f1 = _safe_float((2 * precision * recall) / (precision + recall))
        return {
            "gold_count": gold_count,
            "predicted_count": predicted_count,
            "matched_count": matched_count,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "attribute_checks_passed": attribute_passed,
            "attribute_checks_total": attribute_total,
            "attribute_accuracy": _ratio(attribute_passed, attribute_total),
            "source_url_checks_passed": source_passed,
            "source_url_checks_total": source_total,
            "source_url_accuracy": _ratio(source_passed, source_total),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "company_domain": self.company_domain,
            "evaluated_at": self.evaluated_at,
            "job_id": self.job_id,
            "notes": self.notes,
            "overall": self.overall(),
            "entity_types": {
                entity_type: report.to_dict()
                for entity_type, report in self.entity_types.items()
            },
        }

    def to_markdown(self) -> str:
        overall = self.overall()
        lines = [
            f"# Benchmark Report: {self.benchmark_name}",
            "",
            f"- Company: {self.company_domain or 'n/a'}",
            f"- Job ID: {self.job_id or 'n/a'}",
            f"- Evaluated: {self.evaluated_at[:19].replace('T', ' ')}",
            "",
            "## Overall",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Gold entities | {overall['gold_count']} |",
            f"| Predicted entities | {overall['predicted_count']} |",
            f"| Matched entities | {overall['matched_count']} |",
            f"| Precision | {overall['precision']:.4f} |",
            f"| Recall | {overall['recall']:.4f} |",
            f"| F1 | {overall['f1']:.4f} |",
            f"| Attribute accuracy | {overall['attribute_accuracy']:.4f} |",
            f"| Source URL accuracy | {overall['source_url_accuracy']:.4f} |",
        ]
        for entity_type, report in self.entity_types.items():
            lines.extend([
                "",
                f"## {entity_type}",
                "",
                "| Metric | Value |",
                "|---|---:|",
                f"| Gold | {report.gold_count} |",
                f"| Predicted | {report.predicted_count} |",
                f"| Matched | {report.matched_count} |",
                f"| Precision | {report.precision:.4f} |",
                f"| Recall | {report.recall:.4f} |",
                f"| F1 | {report.f1:.4f} |",
                f"| Attribute accuracy | {report.attribute_accuracy:.4f} |",
                f"| Source URL accuracy | {report.source_url_accuracy:.4f} |",
            ])
            if report.missing:
                lines.extend([
                    "",
                    "Missing expected entities:",
                    *(f"- {name}" for name in report.missing),
                ])
            if report.unexpected:
                lines.extend([
                    "",
                    "Unexpected predicted entities:",
                    *(f"- {name}" for name in report.unexpected),
                ])
        return "\n".join(lines) + "\n"


def _entity_candidate_score(expected: BenchmarkEntity, predicted: ExtractedEntity) -> int:
    expected_keys = expected.name_keys()
    if not expected_keys:
        return 0
    display_key = _normalize_key(predicted.display_name)
    normalized_key = _normalize_key(predicted.normalized_key)
    if display_key == _normalize_key(expected.name):
        return 4
    if normalized_key and normalized_key in expected_keys:
        return 3
    if display_key and display_key in expected_keys:
        return 2
    return 0


def _entity_field_value(entity: ExtractedEntity, field_name: str) -> str:
    if field_name == "display_name":
        return entity.display_name
    if field_name == "confidence":
        return entity.confidence
    if field_name in {"source_url", "first_source_url"}:
        return entity.source_urls[0] if entity.source_urls else ""
    value = entity.attributes.get(field_name, "")
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return str(value or "")


def _field_check_passes(actual: str, rule: dict[str, Any]) -> bool:
    normalized_actual = _normalize_text(actual)
    if "equals" in rule:
        if normalized_actual != _normalize_text(str(rule.get("equals", ""))):
            return False
    if "contains" in rule:
        needle = _normalize_text(str(rule.get("contains", "")))
        if needle not in normalized_actual:
            return False
    if "one_of" in rule:
        options = rule.get("one_of", []) or []
        if normalized_actual not in {_normalize_text(str(option)) for option in options}:
            return False
    return True


def _evaluate_match(expected: BenchmarkEntity, predicted: ExtractedEntity) -> EntityMatchResult:
    result = EntityMatchResult(
        expected_name=expected.name,
        predicted_name=predicted.display_name,
        matched=True,
        expected_notes=expected.notes,
    )
    for field_name, rule in expected.attribute_checks.items():
        result.total_check_count += 1
        actual_value = _entity_field_value(predicted, field_name)
        if _field_check_passes(actual_value, rule):
            result.passed_check_count += 1
        else:
            result.failed_checks.append(field_name)
    for snippet in expected.source_url_contains:
        result.source_url_total += 1
        expected_snippet = _normalize_text(snippet)
        if any(expected_snippet in _normalize_text(url) for url in predicted.source_urls):
            result.source_url_passed += 1
        else:
            result.failed_checks.append(f"source_url_contains:{snippet}")
    return result


def evaluate_entities(
    predicted_entities: dict[str, list[ExtractedEntity]],
    benchmark: BenchmarkCase,
    *,
    job_id: str = "",
) -> EvaluationReport:
    report = EvaluationReport(
        benchmark_name=benchmark.name,
        company_domain=benchmark.company_domain,
        evaluated_at=_utcnow_iso(),
        job_id=job_id,
        notes=benchmark.notes,
    )
    for entity_type, expected_entities in benchmark.entities.items():
        predicted = list(predicted_entities.get(entity_type, []))
        entity_report = EntityTypeReport(
            entity_type=entity_type,
            gold_count=len(expected_entities),
            predicted_count=len(predicted),
        )
        used_indexes: set[int] = set()
        for expected in expected_entities:
            best_index = None
            best_score = 0
            for index, candidate in enumerate(predicted):
                if index in used_indexes:
                    continue
                score = _entity_candidate_score(expected, candidate)
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_index is None:
                entity_report.missing.append(expected.name)
                entity_report.matches.append(EntityMatchResult(expected_name=expected.name, expected_notes=expected.notes))
                continue
            used_indexes.add(best_index)
            match_result = _evaluate_match(expected, predicted[best_index])
            entity_report.matches.append(match_result)
            entity_report.matched_count += 1
            entity_report.attribute_checks_passed += match_result.passed_check_count
            entity_report.attribute_checks_total += match_result.total_check_count
            entity_report.source_url_checks_passed += match_result.source_url_passed
            entity_report.source_url_checks_total += match_result.source_url_total
        entity_report.unexpected = [
            entity.display_name
            for index, entity in enumerate(predicted)
            if index not in used_indexes
        ]
        entity_report.finalize()
        report.entity_types[entity_type] = entity_report
    return report


def evaluate_job(job_id: str, benchmark: BenchmarkCase, storage: JobStorage | None = None) -> EvaluationReport:
    storage = storage or JobStorage()
    predicted_entities = storage.load_entities(job_id)
    return evaluate_entities(predicted_entities, benchmark, job_id=job_id)


def _path_snippet(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or url


def _draft_attribute_checks(entity_type: str, entity: ExtractedEntity) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    if entity_type == "people":
        title = str(entity.attributes.get("title", "") or "").strip()
        linkedin_url = str(entity.attributes.get("linkedin_url", "") or "").strip()
        if title:
            checks["title"] = {"contains": title}
        if linkedin_url:
            checks["linkedin_url"] = {"contains": linkedin_url}
    elif entity_type == "events":
        for key in ("date", "location", "event_type"):
            value = str(entity.attributes.get(key, "") or "").strip()
            if value:
                checks[key] = {"equals": value}
    elif entity_type == "partners":
        category = str(entity.attributes.get("category", "") or "").strip()
        if category:
            checks["category"] = {"equals": category}
    elif entity_type == "resources":
        for key in ("resource_type", "date"):
            value = str(entity.attributes.get(key, "") or "").strip()
            if value:
                checks[key] = {"equals": value}
    elif entity_type == "external_profiles":
        for key in ("domain",):
            value = str(entity.attributes.get(key, "") or "").strip()
            if value:
                checks[key] = {"equals": value}
    return checks


def build_benchmark_draft(
    predicted_entities: dict[str, list[ExtractedEntity]],
    *,
    name: str,
    company_domain: str = "",
    limit_per_type: int = 25,
    entity_types: list[str] | None = None,
) -> BenchmarkCase:
    selected_types = entity_types or sorted(predicted_entities)
    entities: dict[str, list[BenchmarkEntity]] = {}
    for entity_type in selected_types:
        values = predicted_entities.get(entity_type, [])
        if not values:
            continue
        draft_entities: list[BenchmarkEntity] = []
        for entity in sorted(values, key=lambda item: item.display_name.lower())[:limit_per_type]:
            source_url_contains = []
            if entity.source_urls:
                source_url_contains.append(_path_snippet(entity.source_urls[0]))
            draft_entities.append(BenchmarkEntity(
                name=entity.display_name,
                attribute_checks=_draft_attribute_checks(entity_type, entity),
                source_url_contains=source_url_contains,
                notes="Generated draft benchmark entry. Review before using for scoring.",
            ))
        if draft_entities:
            entities[entity_type] = draft_entities
    return BenchmarkCase(
        name=name,
        company_domain=company_domain,
        notes="Generated draft benchmark. Review and trim entries before treating this as gold data.",
        entities=entities,
    )


def build_job_benchmark_draft(
    job_id: str,
    *,
    storage: JobStorage | None = None,
    limit_per_type: int = 25,
    entity_types: list[str] | None = None,
) -> BenchmarkCase:
    storage = storage or JobStorage()
    job = storage.load_job(job_id)
    predicted_entities = storage.load_entities(job_id)
    benchmark_name = f"{job.domain} Benchmark Draft"
    return build_benchmark_draft(
        predicted_entities,
        name=benchmark_name,
        company_domain=job.domain,
        limit_per_type=limit_per_type,
        entity_types=entity_types,
    )


def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_report.json"
    markdown_path = output_dir / "benchmark_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
