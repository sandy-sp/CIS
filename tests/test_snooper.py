# tests/test_snooper.py
import pytest
import responses as resp_mock
from scraper.snooper import Snooper


@resp_mock.activate
def test_llm_txt_found_returns_url_list():
    resp_mock.add(
        resp_mock.GET,
        "https://example.com/llm.txt",
        body="https://example.com/about\nhttps://example.com/services\n",
        status=200,
    )
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/about", "https://example.com/services"]


@resp_mock.activate
def test_llm_txt_not_found_returns_root():
    resp_mock.add(resp_mock.GET, "https://example.com/llm.txt", status=404)
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/"]


@resp_mock.activate
def test_llm_txt_empty_falls_back_to_root():
    resp_mock.add(resp_mock.GET, "https://example.com/llm.txt", body="   \n\n", status=200)
    snooper = Snooper("https://example.com")
    urls = snooper.get_seed_urls()
    assert urls == ["https://example.com/"]


@resp_mock.activate
def test_robots_txt_disallowed_path():
    robots = "User-agent: *\nDisallow: /admin/\nDisallow: /private/\nCrawl-delay: 2\n"
    resp_mock.add(resp_mock.GET, "https://example.com/robots.txt", body=robots, status=200)
    snooper = Snooper("https://example.com")
    snooper.load_robots()
    assert snooper.is_disallowed("https://example.com/admin/dashboard")
    assert snooper.is_disallowed("https://example.com/private/data")
    assert not snooper.is_disallowed("https://example.com/about")
    assert snooper.crawl_delay == 2.0


@resp_mock.activate
def test_robots_txt_missing_uses_default_delay():
    resp_mock.add(resp_mock.GET, "https://example.com/robots.txt", status=404)
    snooper = Snooper("https://example.com")
    snooper.load_robots()
    assert snooper.crawl_delay == 1.0


def test_is_external_off_domain():
    snooper = Snooper("https://example.com")
    assert snooper.is_external("https://linkedin.com/company/example")
    assert snooper.is_external("https://twitter.com/example")
    assert snooper.is_external("https://www.instagram.com/example")


def test_is_external_same_domain_false():
    snooper = Snooper("https://example.com")
    assert not snooper.is_external("https://example.com/about")
    assert not snooper.is_external("https://www.example.com/services")


def test_has_noindex_true():
    snooper = Snooper("https://example.com")
    html = '<meta name="robots" content="noindex, nofollow">'
    assert snooper.has_noindex(html)


def test_has_noindex_false():
    snooper = Snooper("https://example.com")
    assert not snooper.has_noindex("<html><body><p>Normal page</p></body></html>")


def test_has_nofollow_true():
    snooper = Snooper("https://example.com")
    html = '<meta name="robots" content="nofollow">'
    assert snooper.has_nofollow(html)


def test_has_nofollow_false():
    snooper = Snooper("https://example.com")
    assert not snooper.has_nofollow('<meta name="robots" content="index, follow">')
