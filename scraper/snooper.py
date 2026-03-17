# scraper/snooper.py
import re
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class Snooper:
    """Pre-crawl intelligence: llm.txt, robots.txt, noindex/nofollow detection."""

    USER_AGENT = "Business-Scraper/1.0"

    def __init__(self, start_url: str, default_delay: float = 1.0):
        parsed = urlparse(start_url)
        self.scheme = parsed.scheme
        self.domain = re.sub(r"^www\.", "", parsed.netloc)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.crawl_delay = default_delay
        self._rp = urllib.robotparser.RobotFileParser()

    def get_seed_urls(self) -> list[str]:
        """Return URL list from llm.txt, or [root] if not found."""
        try:
            r = requests.get(
                f"{self.base_url}/llm.txt",
                headers={"User-Agent": self.USER_AGENT},
                timeout=10,
            )
            if r.status_code == 200:
                urls = [u.strip() for u in r.text.splitlines() if u.strip().startswith("http")]
                if urls:
                    return urls
        except requests.RequestException:
            pass
        return [f"{self.base_url}/"]

    def load_robots(self) -> None:
        """Fetch and parse robots.txt; set crawl_delay."""
        robots_url = f"{self.base_url}/robots.txt"
        self._rp.set_url(robots_url)
        try:
            r = requests.get(
                robots_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=10,
            )
            if r.status_code == 200:
                self._rp.parse(r.text.splitlines())
            else:
                # No robots.txt — allow everything, keep default delay
                self._rp.parse([])
            delay = self._rp.crawl_delay(self.USER_AGENT) or self._rp.crawl_delay("*")
            if delay:
                self.crawl_delay = float(delay)
        except Exception:
            pass

    def is_disallowed(self, url: str) -> bool:
        return not self._rp.can_fetch(self.USER_AGENT, url)

    def is_external(self, url: str) -> bool:
        parsed = urlparse(url)
        url_domain = re.sub(r"^www\.", "", parsed.netloc)
        return url_domain != self.domain

    def has_noindex(self, html: str) -> bool:
        return self._robots_meta_has(html, "noindex")

    def has_nofollow(self, html: str) -> bool:
        return self._robots_meta_has(html, "nofollow")

    def _robots_meta_has(self, html: str, directive: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if not tag:
            return False
        content = tag.get("content", "").lower()
        return directive in content
