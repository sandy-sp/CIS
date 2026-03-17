import json
import pytest
from unittest.mock import patch, MagicMock
from scraper.scrapy_engine import ScrapyEngine
from models import PageResult

SAMPLE_OUTPUT = json.dumps({
    "url": "https://example.com/services",
    "title": "Services",
    "description": "We do things",
    "language": "en",
    "canonical_url": "https://example.com/services",
    "raw_html": "<h1>Services</h1><p>We do things</p>",
    "markdown": "# Services\n\nWe do things",
    "status": "success",
})


@pytest.fixture
def engine():
    return ScrapyEngine()


def test_scrape_success_parses_json_output(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=SAMPLE_OUTPUT,
            stderr="",
        )
        result = engine.scrape("https://example.com/services")

    assert isinstance(result, PageResult)
    assert result.status == "success"
    assert result.engine_used == "scrapy"
    assert result.title == "Services"
    assert "Services" in result.markdown


def test_scrape_subprocess_failure_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Spider error",
        )
        result = engine.scrape("https://example.com/broken")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()


def test_scrape_timeout_returns_failed(engine):
    import subprocess
    with patch("scraper.scrapy_engine.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 20)):
        result = engine.scrape("https://example.com/slow")

    assert result.status == "failed"
    assert "timeout" in result.skip_reason.lower()


def test_scrape_sets_engine_used(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_OUTPUT, stderr="")
        result = engine.scrape("https://example.com/services")

    assert result.engine_used == "scrapy"


def test_scrape_invalid_json_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        result = engine.scrape("https://example.com/bad")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()
