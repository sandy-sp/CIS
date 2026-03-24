from company_intel.classifier import PageClassifier
from company_intel.models import PageRecord


def _record(url: str, title: str = "", clean_text: str = "") -> PageRecord:
    return PageRecord(
        url=url,
        normalized_url=url,
        domain="example.com",
        path=url.split("example.com", 1)[-1] or "/",
        title=title,
        clean_text=clean_text,
    )


def test_classifier_detects_services():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/services/cloud-migration", title="Cloud Migration Services")
    )
    assert category == "services"
    assert confidence >= 0.9


def test_classifier_detects_people():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/our-team", title="Our Leadership Team")
    )
    assert category == "people"


def test_classifier_detects_people_with_underscore_path():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/our_people/christopher-mcclure", title="Christopher McClure")
    )
    assert category == "people"


def test_classifier_detects_resources_news_subtype():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/news/launch", title="Company News")
    )
    assert category == "resources"
    assert subtype == "news"


def test_classifier_detects_thought_leadership_as_resources_article():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/thought-leadership/fda-guidance", title="FDA Guidance Update")
    )
    assert category == "resources"
    assert subtype == "article"


def test_classifier_detects_press_as_resources_news():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/press/new-ceo", title="Company Names New CEO")
    )
    assert category == "resources"
    assert subtype == "news"


def test_classifier_marks_landing_and_thank_you_pages_as_other():
    category, subtype, confidence = PageClassifier().classify(
        _record("https://example.com/ty/thank-you-demo", title="Thank You")
    )
    assert category == "other"


def test_classifier_detects_case_study_title_under_article_path():
    category, subtype, confidence = PageClassifier().classify(
        _record(
            "https://example.com/thought-leadership/acme-success",
            title="Acme Success Story - A Case Study",
        )
    )
    assert category == "case-studies"
