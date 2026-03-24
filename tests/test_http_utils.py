import requests

from scraper.http_utils import get_with_ssl_fallback


def test_get_with_ssl_fallback_retries_without_verification(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = "ok"

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.exceptions.SSLError("bad cert")
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)

    response = get_with_ssl_fallback("https://example.com", timeout=5)

    assert response.status_code == 200
    assert calls[0].get("verify", True) is True
    assert calls[1]["verify"] is False
