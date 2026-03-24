from __future__ import annotations

import re
from urllib.parse import urlparse

from company_intel.models import PageRecord


_CATEGORY_PATTERNS: list[tuple[str, str, list[str]]] = [
    ("legal", "", [r"/(privacy|terms|cookie|legal|gdpr|disclaimer|imprint|impressum|sitemap)"]),
    ("other", "", [r"/(lp|ty|thank-you)(?:/|$)"]),
    ("contact", "", [r"/(contact|get-in-touch|reach-us|contact-us)"]),
    ("careers", "", [r"/(career|job|join-us|work-with-us|hiring)"]),
    ("people", "", [r"/(team|people|leadership|our[-_]people|experts|staff)"]),
    ("partners", "", [r"/(partner|ecosystem|integration|vendor|alliances)"]),
    ("case-studies", "", [r"/(case-stud|case-study|case-studies|work|portfolio|success-stor|customer-stor|client-stor)"]),
    ("services", "", [r"/(service|solution|offering|capabilit|product)"]),
    ("industries", "", [r"/(industr|market|sector|vertical)"]),
    ("events", "event", [r"/(event|conference|summit|expo|workshop|meetup)"]),
    ("resources", "webinar", [r"/webinars?/"]),
    ("resources", "news", [r"/(news|press)/"]),
    ("resources", "article", [r"/thought-leadership/"]),
    ("resources", "blog", [r"/(blog|insight|article|post|update)"]),
    ("resources", "whitepaper", [r"/(white-paper|whitepaper)"]),
    ("resources", "resource", [r"/resource"]),
    ("company", "", [r"/(about|company|who-we-are|our-story|culture|mission)"]),
]

_TITLE_HINTS = {
    "services": re.compile(r"\b(service|solution|offering|capability)\b", re.IGNORECASE),
    "industries": re.compile(r"\b(industry|industries|markets|sectors)\b", re.IGNORECASE),
    "people": re.compile(r"\b(team|people|leadership|experts)\b", re.IGNORECASE),
    "partners": re.compile(r"\b(partner|ecosystem|integration)\b", re.IGNORECASE),
    "events": re.compile(r"\b(event|conference|summit|webinar|expo)\b", re.IGNORECASE),
    "resources": re.compile(r"\b(blog|news|resource|white paper|webinar)\b", re.IGNORECASE),
    "company": re.compile(r"\b(about|company|culture|mission)\b", re.IGNORECASE),
    "case-studies": re.compile(r"\b(case study|success story|customer story|client story)\b", re.IGNORECASE),
}


class PageClassifier:
    def classify(self, record: PageRecord) -> tuple[str, str, float]:
        path = urlparse(record.normalized_url).path.lower() or "/"
        haystack = " ".join(
            [
                record.title or "",
                record.description or "",
                " ".join(next(iter(item.values())) for item in record.headings if item),
            ]
        )

        if path == "/":
            return "homepage", "", 0.99

        if re.search(r"\b(case study|customer story|success story|client story)\b", record.title or "", re.IGNORECASE):
            return "case-studies", "", 0.99

        for category, subtype, patterns in _CATEGORY_PATTERNS:
            if any(re.search(pattern, path, re.IGNORECASE) for pattern in patterns):
                confidence = 0.95
                if category in _TITLE_HINTS and _TITLE_HINTS[category].search(haystack):
                    confidence = 0.99
                return category, subtype, confidence

        scores = {key: 0 for key in _TITLE_HINTS}
        for category, pattern in _TITLE_HINTS.items():
            if pattern.search(haystack):
                scores[category] += 2
            if pattern.search(record.clean_text[:400]):
                scores[category] += 1

        winner = max(scores.items(), key=lambda item: item[1])
        if winner[1] > 0:
            subtype = "news" if winner[0] == "resources" and "/news/" in path else ""
            return winner[0], subtype, min(0.55 + (winner[1] * 0.1), 0.9)

        return "other", "", 0.25
