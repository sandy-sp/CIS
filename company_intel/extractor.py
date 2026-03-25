from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from company_intel.models import ExtractedEntity, PageRecord


_MONTH_DATE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:[–\-]\d{1,2})?,?\s+\d{4}",
    re.IGNORECASE,
)
_MONTH_ABBR_DATE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\.?\s+\d{1,2}(?:[–\-]\d{1,2})?,?\s+\d{4}",
    re.IGNORECASE,
)
_YEAR_ONLY = re.compile(r"\b(20\d{2})\b")
_LOCATION_HINTS = re.compile(
    r"\b(Boston|Basel|London|San Francisco|Amsterdam|Berlin|Chicago|New York|"
    r"Philadelphia|Washington|Atlanta|Hamburg|Mumbai|North Carolina|USA|UK|Europe|India|Germany|Switzerland|"
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
_MEET_THE_EXPERT = re.compile(
    r"^Meet(?: the Expert:)?\s+(?P<name>[^,]+),\s+(?P<title>.+)$",
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
_PARTNER_PATH_HINT = re.compile(
    r"/(?:partner|partners|ecosystem|integration|integrations|vendor|alliances?)(?:/|$)",
    re.IGNORECASE,
)
_PEOPLE_PATH_HINT = re.compile(
    r"/(?:team|people|leadership|experts|staff|our[-_]people|meet-the-expert(?:-|/|$))(?:/|$)?",
    re.IGNORECASE,
)
_MONTH_NAME_BY_ABBR = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}
_EVENT_GENERIC_LINES = {
    "skip to content",
    "sort by:",
    "employee stories",
    "services white papers blogs news",
}
_PERSON_GENERIC_LINES = {
    "about zifo",
    "careers",
    "contact us",
    "employee stories",
    "our culture",
    "our global teams",
    "our people",
}
_PERSON_ORG_SUFFIXES = {
    "department",
    "information",
    "operations",
    "platform",
    "services",
    "solutions",
    "systems",
    "team",
    "technologies",
}
_CUSTOMER_GENERIC_NAMES = {
    "ai",
    "client",
    "company",
    "customer",
    "electronic data capture",
    "eln",
    "ensuring compliance",
    "exchange",
    "implementing environmental monitoring",
    "investigational new",
    "iss/ise",
    "large language models",
    "ldas",
    "lims",
    "new drug applications",
    "our",
    "pharma success",
    "r&d",
    "reliability",
    "rna-seq data",
    "skip",
    "spatial transcriptomics",
    "us",
    "variant interpretation",
    "we",
    "whole genome sequencing",
    "winning",
}
_SERVICE_ENTITY_HINT = re.compile(
    r"\b(service|services|solution|solutions|consulting|training|support|platform|operations|compliance)\b",
    re.IGNORECASE,
)
_EVENT_RESOURCE_HINT = re.compile(r"\bresources?\b", re.IGNORECASE)
_SERVICE_TITLE_NOISE_HINT = re.compile(
    r"^(?:Head of|Fuel |Jumpstart |Protect |Supercharge |Paradigm Shift)",
    re.IGNORECASE,
)


def _normalize_key(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _clean_title(title: str, domain: str = "") -> str:
    name = re.split(r"\s+\|\s+|\s+-\s+", title or "")[0].strip()
    if not name and domain:
        name = domain.split(".")[0].replace("-", " ").title()
    return name


def _safe_text(value: str | None) -> str:
    if value is None:
        return ""
    return str(value)


def _join_text(parts: list[str | None], *, separator: str = " ") -> str:
    normalized = [_safe_text(part).strip() for part in parts]
    return separator.join(part for part in normalized if part)


def _first_paragraph(record: PageRecord) -> str:
    if record.description:
        return record.description.strip()
    text = _safe_text(record.clean_text).strip()
    if not text:
        return ""
    chunks = [chunk.strip() for chunk in re.split(r"\n{2,}", _safe_text(record.markdown)) if chunk.strip()]
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
        successful = self._filter_primary_language(successful)
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
            if category == "services" and not self._should_extract_service(record):
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
            if not self._is_partner_listing_page(record):
                continue
            current_heading = ""
            for line in _safe_text(record.markdown).splitlines():
                stripped = line.strip()
                heading = self._heading_value(stripped)
                if heading:
                    if self._looks_like_partner_category(heading):
                        current_heading = heading
                    continue
                bullet = self._bullet_value(stripped)
                if not bullet or not current_heading:
                    continue
                partner_name = self._strip_markdown_link(bullet)[0]
                if not self._looks_like_partner_name(partner_name):
                    continue
                entity = ExtractedEntity(
                    entity_type="partner",
                    normalized_key=_normalize_key(partner_name),
                    display_name=partner_name,
                    attributes={"category": current_heading},
                    source_urls=[record.url],
                    evidence_snippets=[partner_name],
                )
                _add_entity(bucket, entity)

    def _extract_people(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if not self._is_people_record(record):
                continue
            markdown_lines = [line.strip() for line in _safe_text(record.markdown).splitlines() if line.strip()]

            for line in markdown_lines:
                parsed = self._parse_person_heading(line)
                if not parsed:
                    continue
                name, title = parsed
                entity = ExtractedEntity(
                    entity_type="person",
                    normalized_key=_normalize_key(name),
                    display_name=name,
                    attributes={"title": title, "linkedin_url": ""},
                    source_urls=[record.url],
                    evidence_snippets=[name],
                    confidence="high",
                )
                _add_entity(bucket, entity)

            for idx, line in enumerate(markdown_lines):
                name = self._clean_markdown_text(line)
                if not self._looks_like_person_name(name):
                    continue
                title = self._person_title_after(markdown_lines, idx)
                if not title:
                    continue
                entity = ExtractedEntity(
                    entity_type="person",
                    normalized_key=_normalize_key(name),
                    display_name=name,
                    attributes={"title": title, "linkedin_url": ""},
                    source_urls=[record.url],
                    evidence_snippets=[name],
                    confidence="high",
                )
                _add_entity(bucket, entity)

            for match in _MD_LINK.finditer(_safe_text(record.markdown)):
                link_text = match.group(1).strip()
                url = match.group(2).strip()
                name = self._guess_person_name(link_text, url)
                if not name:
                    continue
                title = self._find_person_title(markdown_lines, name)
                if not title:
                    continue
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

            for match in _LINKEDIN_PROFILE.finditer(_safe_text(record.markdown)):
                url = match.group(0)
                name = self._slug_to_name(match.group(1))
                if not name:
                    continue
                title = self._find_person_title(markdown_lines, name)
                if not title:
                    continue
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

    def _extract_events(self, records: list[PageRecord], bucket: dict[str, ExtractedEntity]) -> None:
        for record in records:
            if record.page_category != "events":
                continue
            if self._is_event_listing_page(record):
                self._extract_event_listing(record, bucket)
                continue
            if self._is_event_noise_page(record):
                continue
            name = _clean_title(record.title, record.domain)
            if not name or not self._looks_like_event_name(name):
                continue
            date = self._extract_date(record)
            location = self._extract_location(record)
            event_type = self._event_type_from_label(record.title or record.clean_text)
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
            if record.page_category != "case-studies" or record.is_duplicate:
                continue
            search_text = _join_text(
                [
                    record.title,
                    record.description,
                    _safe_text(record.clean_text)[:1200],
                    _safe_text(record.markdown)[:1200],
                ],
                separator="\n",
            )
            for line in [line.strip() for line in search_text.splitlines() if line.strip()]:
                explicit = re.match(
                    r"^(?:customer|client|company|organization)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,'/-]+(?:\s+[A-Z][A-Za-z0-9&.,'/-]+){0,5})$",
                    line,
                    re.IGNORECASE,
                )
                if explicit:
                    company = explicit.group(1).strip(" .,:;")
                    if self._looks_like_customer_name(company, brand):
                        entity = ExtractedEntity(
                            entity_type="customer",
                            normalized_key=_normalize_key(company),
                            display_name=company,
                            attributes={"context": _first_paragraph(record)},
                            source_urls=[record.url],
                            evidence_snippets=[line],
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
        search_text = _join_text([
            record.title,
            record.description,
            _safe_text(record.clean_text)[:1200],
        ])
        match = _MONTH_DATE.search(search_text)
        if match:
            return match.group(0)
        match = _MONTH_ABBR_DATE.search(search_text)
        if match:
            return match.group(0)
        year = _YEAR_ONLY.search(search_text)
        return year.group(1) if year else ""

    def _extract_location(self, record: PageRecord) -> str:
        search_text = _join_text([
            record.title,
            record.description,
            _safe_text(record.clean_text)[:800],
        ])
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
        if not self._looks_like_person_link(url):
            return ""
        words = self._clean_markdown_text(link_text).split()
        if 2 <= len(words) <= 4 and all(word[:1].isupper() for word in words):
            return " ".join(words)
        match = _LINKEDIN_PROFILE.search(url)
        if not match:
            return ""
        return self._slug_to_name(match.group(1))

    def _looks_like_person_link(self, url: str) -> bool:
        if _LINKEDIN_PROFILE.search(url):
            return True
        path = urlparse(url).path.lower()
        return bool(re.search(r"/(?:team|people|leadership|experts|staff|author|bio)/[a-z0-9\-]+/?$", path))

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
            title = self._person_title_after(lines, idx)
            if title:
                return title
        return ""

    def _looks_like_person_name(self, line: str) -> bool:
        stripped = line.strip()
        if stripped.startswith(("* ", "- ", "+ ", "[")):
            return False
        line = self._clean_markdown_text(line)
        if not line or len(line) > 60 or "http" in line:
            return False
        if line.lower() in _PERSON_GENERIC_LINES:
            return False
        if any(char.isdigit() for char in line):
            return False
        if any(symbol in line for symbol in {"|", "/", ":", "@"}):
            return False
        words = [word for word in re.split(r"\s+", line) if word]
        if not (2 <= len(words) <= 4 or (len(words) == 1 and "-" in line)):
            return False
        if words and words[-1].casefold() in _PERSON_ORG_SUFFIXES:
            return False
        if not all(word[0].isupper() for word in words if word[0].isalpha()):
            return False
        if _TITLE_HINTS.search(line) and not any(word.endswith(".") for word in words):
            return False
        return True

    def _parse_person_heading(self, line: str) -> tuple[str, str] | None:
        text = self._clean_markdown_text(line)
        match = _MEET_THE_EXPERT.match(text)
        if not match:
            return None
        name = self._clean_markdown_text(match.group("name"))
        title = self._clean_markdown_text(match.group("title"))
        if not self._looks_like_person_name(name) or not title:
            return None
        return name, title

    def _clean_markdown_text(self, value: str) -> str:
        value = _safe_text(value).strip().lstrip("#").strip()
        text, _ = self._strip_markdown_link(value)
        return " ".join(text.split())

    def _is_partner_listing_page(self, record: PageRecord) -> bool:
        if record.page_category != "partners" or record.is_duplicate:
            return False
        bullet_count = sum(
            1
            for line in _safe_text(record.markdown).splitlines()
            if line.strip().startswith(("* ", "- ", "+ "))
        )
        return bullet_count >= 1 and bool(_PARTNER_PATH_HINT.search(record.path or ""))

    def _looks_like_partner_category(self, heading: str) -> bool:
        heading = self._clean_markdown_text(heading)
        if not heading:
            return False
        if heading.lower() in _SKIP_PARTNER_HEADINGS:
            return False
        if len(heading.split()) > 6:
            return False
        if heading.endswith(".") or "?" in heading:
            return False
        return True

    def _looks_like_partner_name(self, name: str) -> bool:
        name = self._clean_markdown_text(name)
        if not name or len(name) > 60:
            return False
        if name.lower().startswith("zifo provides"):
            return False
        if len(name.split()) > 5:
            return False
        disallowed = {
            "adaptation",
            "audit trail",
            "basics",
            "comparison",
            "creating",
            "creation",
            "data governance",
            "develop",
            "determination",
        }
        lowered = name.lower()
        if any(lowered.startswith(prefix) for prefix in disallowed):
            return False
        return any(char.isalpha() for char in name)

    def _is_people_record(self, record: PageRecord) -> bool:
        return (
            bool(_PEOPLE_PATH_HINT.search(record.path or ""))
            or (
                record.page_category == "people"
                and bool(re.search(r"\b(people|leadership|team|expert|experts|staff)\b", record.title or "", re.IGNORECASE))
            )
        )

    def _person_title_after(self, lines: list[str], index: int) -> str:
        for offset in (1, 2):
            next_index = index + offset
            if next_index >= len(lines):
                break
            candidate = self._clean_markdown_text(lines[next_index])
            if _TITLE_HINTS.search(candidate):
                return candidate
        return ""

    def _is_event_listing_page(self, record: PageRecord) -> bool:
        path = (record.path or "").rstrip("/")
        return path in {"/events", "/company/events"}

    def _is_event_noise_page(self, record: PageRecord) -> bool:
        path = (record.path or "").lower()
        title = self._clean_markdown_text(record.title or "")
        if path.endswith("-resources") or "/resources" in path:
            return True
        if "-meet-with-" in path:
            return True
        if "| meet with" in title.lower():
            return True
        if _EVENT_RESOURCE_HINT.search(title):
            return True
        return False

    def _should_extract_service(self, record: PageRecord) -> bool:
        path = (record.path or "").lower()
        title = self._clean_markdown_text(record.title or "")
        if path.startswith("/services/"):
            return True
        if _SERVICE_TITLE_NOISE_HINT.search(title):
            return False
        if "/solutions/" in path:
            return bool(_SERVICE_ENTITY_HINT.search(title))
        return bool(_SERVICE_ENTITY_HINT.search(title))

    def _extract_event_listing(self, record: PageRecord, bucket: dict[str, ExtractedEntity]) -> None:
        lines = [line.strip() for line in _safe_text(record.markdown).splitlines() if line.strip()]
        for line in lines:
            heading = self._heading_value(line)
            if not heading:
                continue
            name = self._clean_markdown_text(heading)
            if not self._looks_like_event_name(name):
                continue
            date = self._extract_date_from_text(name)
            location = self._extract_location_from_text(name)
            if not date and not location:
                continue
            entity = ExtractedEntity(
                entity_type="event",
                normalized_key=_normalize_key(name),
                display_name=name,
                attributes={
                    "date": date,
                    "location": location,
                    "event_type": "company-hosted",
                    "summary": _first_paragraph(record),
                },
                source_urls=[record.url],
                evidence_snippets=[name],
                confidence="high",
            )
            _add_entity(bucket, entity)

        for index in range(len(lines) - 4):
            day = lines[index]
            month = lines[index + 1]
            if not day.isdigit() or month.rstrip(".").title()[:3].lower() not in _MONTH_NAME_BY_ABBR:
                continue
            name = self._clean_markdown_text(lines[index + 3])
            location = self._clean_markdown_text(lines[index + 4])
            if (
                not name
                or name.lower() in _EVENT_GENERIC_LINES
                or name.startswith("[")
                or not self._looks_like_location(location)
            ):
                continue
            detail_url = ""
            category_label = self._clean_markdown_text(lines[index + 2])
            for followup in lines[index + 5:index + 9]:
                if "View Details" not in followup:
                    continue
                _, detail_url = self._strip_markdown_link(followup)
                break
            month_name = _MONTH_NAME_BY_ABBR[month.rstrip(".").title()[:3].lower()]
            year = self._extract_event_year(name, detail_url or record.url)
            date = f"{month_name} {int(day)}, {year}" if year else f"{month_name} {int(day)}"
            summary = location
            source_urls = [url for url in [detail_url, record.url] if url]
            entity = ExtractedEntity(
                entity_type="event",
                normalized_key=_normalize_key(name),
                display_name=name,
                attributes={
                    "date": date,
                    "location": location,
                    "event_type": self._event_type_from_label(category_label),
                    "summary": summary,
                },
                source_urls=source_urls,
                evidence_snippets=[name],
                confidence="high",
            )
            _add_entity(bucket, entity)

    def _looks_like_event_name(self, value: str) -> bool:
        value = self._clean_markdown_text(value)
        if not value or len(value) > 120:
            return False
        if value.lower() in _EVENT_GENERIC_LINES:
            return False
        if value.startswith("[") or value.endswith(":"):
            return False
        return any(char.isalpha() for char in value) and (
            bool(_YEAR_ONLY.search(value))
            or any(token in value.lower() for token in ("event", "conference", "summit", "exchange", "labs", "symposium"))
        )

    def _looks_like_location(self, value: str) -> bool:
        value = self._clean_markdown_text(value)
        if not value or len(value) > 80:
            return False
        if value.startswith("["):
            return False
        return bool(_LOCATION_HINTS.search(value)) or "," in value

    def _extract_date_from_text(self, value: str) -> str:
        match = _MONTH_DATE.search(value)
        if match:
            return match.group(0)
        match = _MONTH_ABBR_DATE.search(value)
        if match:
            return match.group(0)
        year = _YEAR_ONLY.search(value)
        return year.group(1) if year else ""

    def _extract_location_from_text(self, value: str) -> str:
        match = _LOCATION_HINTS.search(value)
        return match.group(1) if match else ""

    def _extract_event_year(self, name: str, url: str) -> str:
        for value in (name, url):
            match = _YEAR_ONLY.search(value or "")
            if match:
                return match.group(1)
        return ""

    def _event_type_from_label(self, label: str) -> str:
        label = self._clean_markdown_text(label).lower()
        if any(token in label for token in ("zifo", "on demand", "hosted")):
            return "company-hosted"
        return "industry"

    def _looks_like_customer_name(self, name: str, brand: str) -> bool:
        normalized = " ".join(name.split()).strip(" .,:;")
        if not normalized:
            return False
        lowered = normalized.lower()
        if lowered == brand or lowered in _CUSTOMER_GENERIC_NAMES:
            return False
        if len(normalized.split()) == 1 and len(normalized) < 4:
            return False
        return True

    def _filter_primary_language(self, records: list[PageRecord]) -> list[PageRecord]:
        language_counts = Counter(
            record.language
            for record in records
            if record.source_type == "internal" and record.language
        )
        if not language_counts:
            return records
        primary_language, _ = language_counts.most_common(1)[0]
        return [
            record
            for record in records
            if record.source_type != "internal" or not record.language or record.language == primary_language
        ]
