# scraper/snooper.py
import re
import urllib.robotparser
import xml.etree.ElementTree as ET
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
        self.has_llm_txt = False
        self.has_robots_txt = False
        self.seed_source = "discovery"
        self._rp = urllib.robotparser.RobotFileParser()

    def get_seed_urls(self) -> list[str]:
        """Return seed URLs from llm.txt, sitemap, or root discovery."""
        llm_urls = self._fetch_llm_urls()
        if llm_urls:
            self.has_llm_txt = True
            self.seed_source = "llm.txt"
            return llm_urls

        sitemap_urls = self._fetch_sitemap_urls()
        if sitemap_urls:
            self.seed_source = "sitemap"
            return sitemap_urls

        self.seed_source = "discovery"
        return [f"{self.base_url}/"]

    def get_discovery_urls(self) -> list[str]:
        """Return a combined seed set from llm.txt, sitemap, and root."""
        urls: list[str] = [f"{self.base_url}/"]
        llm_urls = self._fetch_llm_urls()
        if llm_urls:
            self.has_llm_txt = True
            urls.extend(llm_urls)
        sitemap_urls = self._fetch_sitemap_urls()
        if sitemap_urls:
            urls.extend(sitemap_urls)
        deduped = list(dict.fromkeys(urls))
        if llm_urls and sitemap_urls:
            self.seed_source = "llm.txt+sitemap+root"
        elif llm_urls:
            self.seed_source = "llm.txt+root"
        elif sitemap_urls:
            self.seed_source = "sitemap+root"
        else:
            self.seed_source = "discovery"
        return deduped

    def _fetch_llm_urls(self) -> list[str]:
        """Return http URLs listed in llm.txt, if present."""
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
        return []

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
                self.has_robots_txt = True
                self._rp.parse(r.text.splitlines())
            else:
                # No robots.txt — allow everything, keep default delay
                self._rp.parse([])
            delay = self._rp.crawl_delay(self.USER_AGENT) or self._rp.crawl_delay("*")
            if delay:
                self.crawl_delay = float(delay)
        except Exception:
            self._rp.parse([])  # allow all when robots.txt is unreachable

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

    def _fetch_sitemap_urls(self) -> list[str]:
        sitemap_roots = list(self._rp.site_maps() or [])
        if not sitemap_roots:
            for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap"):
                try:
                    r = requests.get(
                        f"{self.base_url}{path}",
                        headers={"User-Agent": self.USER_AGENT},
                        timeout=10,
                    )
                    text = r.text.lower()
                    if r.status_code == 200 and ("<urlset" in text or "<sitemapindex" in text):
                        sitemap_roots.append(f"{self.base_url}{path}")
                        break
                except requests.RequestException:
                    pass

        all_urls: list[str] = []
        for sitemap_url in sitemap_roots:
            all_urls.extend(self._parse_sitemap(sitemap_url))

        same_domain_urls = [url for url in all_urls if not self.is_external(url)]
        return list(dict.fromkeys(same_domain_urls))

    def _parse_sitemap(self, url: str, depth: int = 0) -> list[str]:
        if depth > 4:
            return []

        try:
            r = requests.get(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=15,
            )
            if r.status_code != 200:
                return []

            root = ET.fromstring(r.content)
        except Exception:
            return []

        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag[1:].split("}", 1)[0]

        def _tag(name: str) -> str:
            return f"{{{namespace}}}{name}" if namespace else name

        urls: list[str] = []
        for sitemap in root.findall(_tag("sitemap")):
            loc = sitemap.find(_tag("loc"))
            if loc is not None and loc.text:
                urls.extend(self._parse_sitemap(loc.text.strip(), depth + 1))

        for url_el in root.findall(_tag("url")):
            loc = url_el.find(_tag("loc"))
            if loc is not None and loc.text:
                urls.append(loc.text.strip())

        return urls
