from __future__ import annotations

import re
from urllib.parse import urlparse

from company_intel.models import ExtractedEntity, PageRecord


_MONTH_DATE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:[–\-]\d{1,2})?,?\s+\d{4}",
    re.IGNORECASE,
)
_YEAR_ONLY = re.compile(r"\b(20\d{2})\b")
_LOCATION_HINTS = re.compile(
    r"\b(Boston|Basel|London|San Francisco|Amsterdam|Berlin|Chicago|New York|"
    r"Philadelphia|Washington|Atlanta|USA|UK|Europe|India|Germany|Switzerland|"
    r"Virtual|Online|Remote)\b",
    re.IGNORECASE,
)
_TITLE_HINTS = re.compile(
    r"\b(CEO|CTO|COO|CFO|Chief|VP|Vice President|Director|Head|Lead|Manager|Consultant|"
    r"Engineer|Scientist|Partner|Founder|President|Officer|Operations|Sales|Marketing)\b",
    re.IGNORECASE,
)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_LINKEDIN_PROFILE = re.compile(
    r"https?://(?:www\.|[a-z]{2}\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?",
    re.IGNORECASE,
)
_CUSTOMER_PATTERNS = [
    re.compile(
        r"^(?:customer|client|company|organization)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,'/-]+(?:\s+[A-Z][A-Za-z0-9&.,'/-]+){0,5})$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:customer|client|company|organization)\s*[:\-]?\s*([A-Z][A-Za-z0-9&.,'/-]+(?:\s+[A-Z][A-Za-z0-9&.,'/-]+){0,5})"
    ),
    re.compile(
        r"\b(?:for|with|partnered with)\s+([A-Z][A-Za-z0-9&.,'/-]+(?:\s+[A-Z][A-Za-z0-9&.,'/-]+){0,5})"
    ),
]
_SKIP_PARTNER_HEADINGS = {
    "request further information now!",
    "project inquiry",
    "contact us",
    "request information",
    "book a demo",
    "demo request",
}


def _normalize_key(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _clean_title(title: str, domain: str = "") -> str:
    name = re.split(r"\s+\|\s+|\s+-\s+", title or "")[0].strip()
    if not name and domain:
        name = domain.split(".")[0].replace("-", " ").title()
    return name


def _first_paragraph(record: PageRecord) -> str:
    if record.description:
        return record.description.strip()
    text = (record.clean_text or "").strip()
    if not text:
        return ""
    chunks = [chunk.strip() for chunk in re.split(r"\n{2,}", record.markdown) if chunk.strip()]
    if chunks:
        chunk = re.sub(r"^[#>\-\*\+\d\.\s]+", "", chunks[0]).strip()
        return re.sub(r"\s+", " ", chunk)[:280]
    return " ".join(text.split()[:45])


def _add_entity(bucket: dict[str, ExtractedEntity], entity: ExtractedEntity) -> None:
    existing = bucket.get(entity.normalized_key)
    if not existing:
        bucket[entity.normalized_key] = entity
        return
    existing.source_urls = sorted(set(existing.source_urls + entity.source_urls))
    existing.evidence_snippets = sorted(set(existing.evidence_snippets + entity.evidence_snippets))
    for key, value in entity.attributes.items():
        if not existing.attributes.get(key) and value:
            existing.attributes[key] = value


class UniversalExtractor:
    def extract(self, records: list[PageRecord], company_domain: str) -> dict[str, list[ExtractedEntity]]:
        successful = [record for record in records if record.status == "success"]
        buckets: dict[str, dict[str, ExtractedEntity]] = {
            "company_profile": {},
            "services": {},
            "industries": {},
            "case_studies": {},
            "partners": {},
            "customers": {},
            "people": {},
            "events": {},
            "resources": {},
            "external_profiles": {},
        }

        self._extract_company_profile(successful, company_domain, buckets["company_profile"])
        self._extract_catalog(successful, "services", buckets["services"])
        self._extract_catalog(successful, "industries", buckets["industries"])
        self._extract_catalog(successful, "case-studies", buckets["case_studies"], entity_type="case_study")
        self._extract_resources(successful, buckets["resources"])
        self._extract_partners(successful, buckets["partners"])
        self._extract_people(successful, buckets["people"])
        self._extract_events(successful, buckets["events"])
        self._extract_customers(successful, buckets["customers"], company_domain)
        self._extract_external(records, buckets["external_profiles"])

        return {
            key: sorted(values.values(), key=lambda entity: entity.display_name.lower())
            for key, values in buckets.items()
        }

    def _extract_company_profile(self, records: list[PageRecord], company_domain: str,
                                 bucket: dict[str, ExtractedEntity]) -> None:
        candidates = [record for record in records if record.page_category in {"homepage", "company"}]
        if not candidates:
            return
        record = max(candidates, key=lambda item: item.word_count)
        name = _clean_title(record.title, company_domain)
        entity = ExtractedEntity(
            entity_type="company_profile",
            normalized_key=_normalize_key(name or company_domain),
            display_name=name or company_domain,
            attributes={
                "website": f"https://{company_domain}",
                "summary": _first_paragraph(record),
            },
            source_urls=[record.url],
            evidence_snippets=[_first_paragraph(record)],
            confidence="high",
        )
        _add_entity(bucket, entity)

    def _extract_catalog(self, records: list[PageRecord], category: str,
                         bucket: dict[str, ExtractedEntity], entity_type: str | None = None) -> None:
        entity_type = entity_type or category[:-1]
        for record in records:
            if record.page_category != category or record.is_duplicate:
                continue
            name = _clean_title(record.title, record.domain)
            if not name:
                continue
            entity = ExtractedEntity(
                entity_type=entity_type,
                normalized_key=_normalize_key(name),
                display_name=name,
                attributes={
                    "summary": _first_paragraph(record),
                    "subtype": record.page_subtype,
                },
                source_urls=[record.url],
                evidence_snippets=[_first_paragraph(record)],
                confidence="high" if category in {"services", "industries"} else "medium",
            )
            _add_entity(bucket, entity)

    def _extract_resources(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if record.page_category != "resources" or record.is_duplicate:
                continue
            name = _clean_title(record.title, record.domain)
            if not name:
                continue
            date = self._extract_date(record)
            entity = ExtractedEntity(
                entity_type="resource",
                normalized_key=_normalize_key(f"{record.page_subtype}-{name}"),
                display_name=name,
                attributes={
                    "resource_type": record.page_subtype or "resource",
                    "date": date,
                    "summary": _first_paragraph(record),
                },
                source_urls=[record.url],
                evidence_snippets=[_first_paragraph(record)],
            )
            _add_entity(bucket, entity)

    def _extract_partners(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if record.page_category != "partners":
                continue
            current_heading = ""
            found_any = False
            for line in record.markdown.splitlines():
                stripped = line.strip()
                heading = self._heading_value(stripped)
                if heading:
                    if heading.lower() not in _SKIP_PARTNER_HEADINGS:
                        current_heading = heading
                    continue
                bullet = self._bullet_value(stripped)
                if not bullet:
                    continue
                partner_name = self._strip_markdown_link(bullet)[0]
                if not partner_name or len(partner_name) > 80:
                    continue
                found_any = True
                entity = ExtractedEntity(
                    entity_type="partner",
                    normalized_key=_normalize_key(partner_name),
                    display_name=partner_name,
                    attributes={"category": current_heading},
                    source_urls=[record.url],
                    evidence_snippets=[partner_name],
                )
                _add_entity(bucket, entity)
            if not found_any:
                name = _clean_title(record.title, record.domain)
                if name:
                    entity = ExtractedEntity(
                        entity_type="partner",
                        normalized_key=_normalize_key(name),
                        display_name=name,
                        attributes={"category": ""},
                        source_urls=[record.url],
                        evidence_snippets=[_first_paragraph(record)],
                    )
                    _add_entity(bucket, entity)

    def _extract_people(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            markdown_lines = [line.strip() for line in record.markdown.splitlines() if line.strip()]

            for match in _MD_LINK.finditer(record.markdown):
                link_text = match.group(1).strip()
                url = match.group(2).strip()
                name = self._guess_person_name(link_text, url)
                if not name:
                    continue
                title = self._find_person_title(markdown_lines, name)
                entity = ExtractedEntity(
                    entity_type="person",
                    normalized_key=_normalize_key(url or name),
                    display_name=name,
                    attributes={"title": title, "linkedin_url": url},
                    source_urls=[record.url],
                    evidence_snippets=[name],
                    confidence="high",
                )
                _add_entity(bucket, entity)

            for match in _LINKEDIN_PROFILE.finditer(record.markdown):
                url = match.group(0)
                name = self._slug_to_name(match.group(1))
                if not name:
                    continue
                title = self._find_person_title(markdown_lines, name)
                entity = ExtractedEntity(
                    entity_type="person",
                    normalized_key=_normalize_key(url),
                    display_name=name,
                    attributes={"title": title, "linkedin_url": url},
                    source_urls=[record.url],
                    evidence_snippets=[name],
                    confidence="medium",
                )
                _add_entity(bucket, entity)

            if record.page_category != "people":
                continue
            for idx, line in enumerate(markdown_lines):
                if not self._looks_like_person_name(line):
                    continue
                title = markdown_lines[idx + 1] if idx + 1 < len(markdown_lines) and _TITLE_HINTS.search(markdown_lines[idx + 1]) else ""
                entity = ExtractedEntity(
                    entity_type="person",
                    normalized_key=_normalize_key(line),
                    display_name=line,
                    attributes={"title": title, "linkedin_url": ""},
                    source_urls=[record.url],
                    evidence_snippets=[line],
                    confidence="medium",
                )
                _add_entity(bucket, entity)

    def _extract_events(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if record.page_category != "events":
                continue
            name = _clean_title(record.title, record.domain)
            if not name:
                continue
            date = self._extract_date(record)
            location = self._extract_location(record)
            event_type = "company-hosted" if "register" in record.clean_text.lower() or "join us" in record.clean_text.lower() else "industry"
            entity = ExtractedEntity(
                entity_type="event",
                normalized_key=_normalize_key(name),
                display_name=name,
                attributes={
                    "date": date,
                    "location": location,
                    "event_type": event_type,
                    "summary": _first_paragraph(record),
                },
                source_urls=[record.url],
                evidence_snippets=[_first_paragraph(record)],
            )
            _add_entity(bucket, entity)

    def _extract_customers(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity], company_domain: str) -> None:
        brand = company_domain.split(".")[0].replace("-", " ").lower()
        for record in records:
            if record.page_category not in {"case-studies", "resources", "company"}:
                continue
            search_text = "\n".join([record.title, record.description, record.clean_text[:1200], record.markdown[:1200]])
            for line in [line.strip() for line in search_text.splitlines() if line.strip()]:
                explicit = re.match(
                    r"^(?:customer|client|company|organization)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,'/-]+(?:\s+[A-Z][A-Za-z0-9&.,'/-]+){0,5})$",
                    line,
                    re.IGNORECASE,
                )
                if explicit:
                    company = explicit.group(1).strip(" .,:;")
                    if company and company.lower() != brand:
                        entity = ExtractedEntity(
                            entity_type="customer",
                            normalized_key=_normalize_key(company),
                            display_name=company,
                            attributes={"context": _first_paragraph(record)},
                            source_urls=[record.url],
                            evidence_snippets=[line],
                        )
                        _add_entity(bucket, entity)
            for pattern in _CUSTOMER_PATTERNS:
                for match in pattern.finditer(search_text):
                    company = match.group(1).strip(" .,:;")
                    if not company or company.lower() == brand:
                        continue
                    if company.lower() in {"our", "we", "us"}:
                        continue
                    entity = ExtractedEntity(
                        entity_type="customer",
                        normalized_key=_normalize_key(company),
                        display_name=company,
                        attributes={"context": _first_paragraph(record)},
                        source_urls=[record.url],
                        evidence_snippets=[match.group(0)],
                    )
                    _add_entity(bucket, entity)

    def _extract_external(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if record.source_type != "external":
                continue
            parsed = urlparse(record.url)
            name = _clean_title(record.title, parsed.netloc)
            entity = ExtractedEntity(
                entity_type="external_profile",
                normalized_key=_normalize_key(record.url),
                display_name=name or parsed.netloc,
                attributes={"domain": parsed.netloc, "url": record.url},
                source_urls=[record.url],
                evidence_snippets=[_first_paragraph(record) or parsed.netloc],
            )
            _add_entity(bucket, entity)

    def _extract_date(self, record: PageRecord) -> str:
        search_text = " ".join([record.title, record.description, record.clean_text[:1200]])
        match = _MONTH_DATE.search(search_text)
        if match:
            return match.group(0)
        year = _YEAR_ONLY.search(search_text)
        return year.group(1) if year else ""

    def _extract_location(self, record: PageRecord) -> str:
        search_text = " ".join([record.title, record.description, record.clean_text[:800]])
        match = _LOCATION_HINTS.search(search_text)
        return match.group(1) if match else ""

    def _heading_value(self, line: str) -> str:
        if line.startswith("##"):
            return line.lstrip("#").strip()
        return ""

    def _bullet_value(self, line: str) -> str:
        if line.startswith(("* ", "- ", "+ ")):
            return line[2:].strip()
        return ""

    def _strip_markdown_link(self, value: str) -> tuple[str, str]:
        match = re.match(r"\[(.+?)\]\((https?://[^\)]+)\)", value)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return value, ""

    def _guess_person_name(self, link_text: str, url: str) -> str:
        words = link_text.split()
        if 2 <= len(words) <= 4 and all(word[:1].isupper() for word in words):
            return link_text
        match = _LINKEDIN_PROFILE.search(url)
        if not match:
            return ""
        return self._slug_to_name(match.group(1))

    def _slug_to_name(self, slug: str) -> str:
        parts = []
        for part in slug.replace("_", "-").split("-"):
            if not part:
                continue
            if any(ch.isdigit() for ch in part) and len(part) > 3:
                continue
            parts.append(part.capitalize())
        if 2 <= len(parts) <= 4:
            return " ".join(parts)
        return ""

    def _find_person_title(self, lines: list[str], name: str) -> str:
        for idx, line in enumerate(lines):
            if name.lower() not in line.lower():
                continue
            for offset in (1, 2):
                next_idx = idx + offset
                if next_idx >= len(lines):
                    break
                candidate = lines[next_idx].strip()
                if _TITLE_HINTS.search(candidate):
                    return candidate
        return ""

    def _looks_like_person_name(self, line: str) -> bool:
        if line.startswith("#") or len(line) > 60 or "http" in line:
            return False
        words = [word for word in re.split(r"\s+", line) if word]
        if not 2 <= len(words) <= 4:
            return False
        return all(word[0].isupper() for word in words if word[0].isalpha())
