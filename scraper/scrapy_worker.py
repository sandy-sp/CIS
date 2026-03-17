"""
Standalone Scrapy subprocess worker.
Usage: python scraper/scrapy_worker.py <url>
Prints a single JSON object to stdout.
"""
import json
import sys
import html2text
import scrapy
from scrapy.crawler import CrawlerProcess
from bs4 import BeautifulSoup


class SinglePageSpider(scrapy.Spider):
    name = "single_page"
    custom_settings = {
        "LOG_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 20,
        "DEPTH_LIMIT": 1,
        "ROBOTSTXT_OBEY": False,
        "USER_AGENT": "Business-Scraper/1.0",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(self, url: str, result_container: list, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = [url]
        self.result_container = result_container

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove nav, footer, ads
        for tag in soup.select("nav, footer, header, .cookie-banner, #cookie-notice, .ads"):
            tag.decompose()

        clean_html = str(soup)

        converter = html2text.HTML2Text()
        converter.ignore_images = False
        converter.body_width = 0
        converter.unicode_snob = True
        markdown = converter.handle(clean_html)

        title = response.css("title::text").get("").strip()
        description = response.css('meta[name="description"]::attr(content)').get("").strip()
        canonical = response.css('link[rel="canonical"]::attr(href)').get("").strip()
        lang = response.css("html::attr(lang)").get("").strip()

        self.result_container.append({
            "url": response.url,
            "title": title,
            "description": description,
            "language": lang,
            "canonical_url": canonical or response.url,
            "raw_html": clean_html,
            "markdown": markdown,
            "status": "success",
        })


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "failed", "skip_reason": "no URL provided"}))
        sys.exit(1)

    target_url = sys.argv[1]
    container: list = []

    process = CrawlerProcess()
    process.crawl(SinglePageSpider, url=target_url, result_container=container)
    process.start()

    if container:
        print(json.dumps(container[0]))
    else:
        print(json.dumps({"url": target_url, "status": "failed", "skip_reason": "scrapy no result"}))
