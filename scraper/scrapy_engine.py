import json
import subprocess
import sys
from pathlib import Path

from models import PageResult

_WORKER = str(Path(__file__).parent / "scrapy_worker.py")
_TIMEOUT = 25  # seconds (scrapy internal timeout 20s + buffer)


class ScrapyEngine:
    """Fallback scraper: spawns scrapy_worker.py as a subprocess."""

    def scrape(self, url: str) -> PageResult:
        result = PageResult(url=url, engine_used="scrapy")
        try:
            proc = subprocess.run(
                [sys.executable, _WORKER, url],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            if proc.returncode != 0:
                result.status = "failed"
                result.skip_reason = f"scrapy exit {proc.returncode}: {proc.stderr[:200]}"
                return result

            data = json.loads(proc.stdout)
            result.title = data.get("title", "")
            result.description = data.get("description", "")
            result.language = data.get("language", "")
            result.canonical_url = data.get("canonical_url", "") or url
            result.raw_html = data.get("raw_html", "")
            result.markdown = data.get("markdown", "")
            result.status = data.get("status", "failed")
            if result.status != "success":
                result.skip_reason = data.get("skip_reason", "scrapy failed")

        except subprocess.TimeoutExpired:
            result.status = "failed"
            result.skip_reason = "scrapy timeout"
        except json.JSONDecodeError as exc:
            result.status = "failed"
            result.skip_reason = f"scrapy bad json: {exc}"
        except Exception as exc:
            result.status = "failed"
            result.skip_reason = f"scrapy error: {exc}"

        return result
