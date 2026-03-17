# scraper/queue_manager.py
import hashlib
from urllib.parse import urlparse, urlencode, parse_qs, parse_qsl

import redis as redis_lib


class QueueManager:
    """Redis-backed crawl queue with URL dedup, content hash dedup, and state persistence."""

    LOG_MAX = 500

    def __init__(self, domain: str, redis_client=None, redis_url: str = "redis://localhost:6379"):
        self.domain = domain
        self._r = redis_client or redis_lib.from_url(redis_url, decode_responses=True)
        self._keys = {
            "queue": f"{domain}:queue",
            "enqueued": f"{domain}:enqueued",   # dedup — prevents re-enqueueing
            "visited": f"{domain}:visited",      # URLs actually scraped (resume state)
            "content_hashes": f"{domain}:content_hashes",
            "failed": f"{domain}:failed",
            "external": f"{domain}:external",
            "log": f"{domain}:log",
            "meta": f"{domain}:meta",
        }

    def enqueue(self, url: str) -> bool:
        """Add URL to queue if not already enqueued. Returns True if added.

        Uses a separate 'enqueued' set for dedup — does NOT mark the URL as
        scraped. Call mark_visited() after successful scraping.
        """
        norm = self.normalize(url)
        if self._r.sismember(self._keys["enqueued"], norm):
            return False
        self._r.sadd(self._keys["enqueued"], norm)
        self._r.rpush(self._keys["queue"], norm)
        return True

    def dequeue(self) -> str | None:
        return self._r.lpop(self._keys["queue"])

    def mark_visited(self, url: str) -> None:
        """Mark URL as actually scraped (called after scraping completes)."""
        self._r.sadd(self._keys["visited"], self.normalize(url))

    def is_visited(self, url: str) -> bool:
        """True if URL has been scraped (not just enqueued)."""
        return bool(self._r.sismember(self._keys["visited"], self.normalize(url)))

    def mark_failed(self, url: str) -> None:
        self._r.sadd(self._keys["failed"], self.normalize(url))

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def is_duplicate_content(self, hash_value: str) -> bool:
        return bool(self._r.sismember(self._keys["content_hashes"], hash_value))

    def add_content_hash(self, hash_value: str) -> None:
        self._r.sadd(self._keys["content_hashes"], hash_value)

    def save_external(self, url: str) -> None:
        domain = urlparse(url).netloc.lstrip("www.")
        self._r.hset(self._keys["external"], f"{domain}::{url}", "1")

    def get_external_links(self) -> dict[str, list[str]]:
        raw = self._r.hkeys(self._keys["external"])
        result: dict[str, list[str]] = {}
        for entry in raw:
            domain, _, url = entry.partition("::")
            result.setdefault(domain, [])
            if url not in result[domain]:
                result[domain].append(url)
        return result

    def log(self, line: str) -> None:
        self._r.lpush(self._keys["log"], line)
        self._r.ltrim(self._keys["log"], 0, self.LOG_MAX - 1)

    def get_log_lines(self, n: int) -> list[str]:
        return self._r.lrange(self._keys["log"], 0, n - 1)

    def update_meta(self, **kwargs) -> None:
        self._r.hset(self._keys["meta"], mapping={k: str(v) for k, v in kwargs.items()})

    def get_meta(self) -> dict:
        return self._r.hgetall(self._keys["meta"])

    def has_existing_state(self) -> bool:
        return bool(self._r.llen(self._keys["queue"]) or self._r.scard(self._keys["enqueued"]))

    def flush(self) -> None:
        for key in self._keys.values():
            self._r.delete(key)

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")
