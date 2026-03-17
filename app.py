# app.py
# IMPORTANT: All helper functions are defined BEFORE any Streamlit UI code
# that calls them. Streamlit reruns the entire script top-to-bottom on each
# interaction, so function definitions must precede their call sites.
import os
import queue
import threading
import time
import asyncio
from urllib.parse import urlparse

import redis
import streamlit as st

from models import PageResult
from scraper.snooper import Snooper
from scraper.queue_manager import QueueManager
from scraper.hybrid_scraper import HybridScraper
from scraper.exporter import Exporter

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


# ===========================================================================
# SECTION 1: Helper functions — all defined before any Streamlit UI code
# ===========================================================================

def _run_crawl(start_url: str, max_pages: int, rate_limit: float,
               result_queue: queue.Queue, cancel_flag: list) -> None:
    """Runs in a daemon thread with its own asyncio event loop.

    Threading model:
    - This function runs in a background daemon thread (started by _start_crawl).
    - It creates and owns its own asyncio event loop via asyncio.run().
    - Results are placed onto a thread-safe queue.Queue.
    - Streamlit polls this queue on each rerun (st.rerun()) — the thread is
      NOT affected by Streamlit reruns. Generator state lives in this thread.
    - cancel_flag is a shared mutable list; appending True signals cancellation.
    """
    async def _crawl():
        parsed = urlparse(start_url)
        domain = parsed.netloc.lstrip("www.")

        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        qm = QueueManager(domain, redis_client=redis_client)

        snooper = Snooper(start_url, default_delay=rate_limit)
        snooper.load_robots()
        snooper.crawl_delay = max(rate_limit, snooper.crawl_delay)

        seed_urls = snooper.get_seed_urls()
        for url in seed_urls:
            qm.enqueue(url)
        qm.update_meta(pages_found=len(seed_urls), pages_done=0, total_words=0)

        scraper = HybridScraper(qm, snooper, max_pages=max_pages, cancel_flag=cancel_flag)
        async for result in scraper.crawl(start_url):
            result_queue.put(result)

        result_queue.put(None)  # sentinel: crawl complete

    asyncio.run(_crawl())


def _start_crawl(url: str, max_pages: int, rate_limit: float) -> None:
    """Reset session state and launch background crawl thread.

    Note: resume vs. fresh-start is handled before calling this function (the
    caller flushes Redis on fresh start). This function always resets in-memory
    session state and starts a new thread polling from whatever is in the queue.
    """
    st.session_state.crawl_running = True
    st.session_state.results = []
    st.session_state.log_lines = []
    st.session_state.stats = {
        "scraped": 0, "failed": 0, "skipped": 0,
        "words": 0, "crawl4ai": 0, "scrapy": 0,
    }
    st.session_state.cancel_flag = []
    st.session_state.zip_bytes = None
    st.session_state.domain = urlparse(url).netloc.lstrip("www.")

    result_q: queue.Queue = queue.Queue()
    st.session_state.result_queue = result_q

    threading.Thread(
        target=_run_crawl,
        args=(url, max_pages, rate_limit, result_q, st.session_state.cancel_flag),
        daemon=True,
    ).start()


def _update_stats(result: PageResult) -> None:
    s = st.session_state.stats
    if result.status == "success":
        s["scraped"] += 1
        s["words"] += result.word_count
        s["scrapy" if result.engine_used == "scrapy" else "crawl4ai"] += 1
    elif result.status == "failed":
        s["failed"] += 1
    elif result.status == "skipped":
        s["skipped"] += 1


def _append_log(result: PageResult) -> None:
    if result.status == "success":
        tag = "[WARN]" if result.engine_used == "scrapy" else "[OK]  "
        line = f"{tag} {result.url} [{result.engine_used}] {result.word_count}w"
    elif result.status == "skipped":
        line = f"[SKIP] {result.url}  {result.skip_reason}"
    else:
        line = f"[FAIL] {result.url}  {result.skip_reason}"
    lines = [line] + st.session_state.log_lines
    st.session_state.log_lines = lines[:50]


def _build_zip() -> None:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        qm = QueueManager(st.session_state.domain, redis_client=redis_client)
        external = qm.get_external_links()
        exporter = Exporter(st.session_state.domain)
        st.session_state.zip_bytes = exporter.build_zip(st.session_state.results, external)
    except Exception as exc:
        st.error(f"Failed to build zip: {exc}")


# ===========================================================================
# SECTION 2: Streamlit UI — runs after all functions are defined above
# ===========================================================================

st.set_page_config(page_title="Business Scraper", layout="wide")
st.title("Business Scraper")
st.caption("Crawl a company website and download RAG-ready Markdown files.")

# --- Session state init (idempotent — runs every rerun) ---
_defaults = {
    "crawl_running": False,
    "results": [],
    "log_lines": [],
    "stats": {"scraped": 0, "failed": 0, "skipped": 0, "words": 0, "crawl4ai": 0, "scrapy": 0},
    "cancel_flag": [],
    "result_queue": None,
    "domain": "",
    "zip_bytes": None,
    "pending_resume": None,
}
for key, default in _defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- Input form ---
with st.form("crawl_form"):
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        url_input = st.text_input("Target URL", placeholder="https://example.com")
    with col2:
        max_pages = st.number_input("Max pages", min_value=10, max_value=5000, value=500, step=50)
    with col3:
        rate_limit = st.number_input("Rate limit (s)", min_value=0.5, max_value=10.0, value=1.0, step=0.5)
    submitted = st.form_submit_button("Start Crawl")

# --- Handle form submission (check for existing crawl state) ---
if submitted and url_input and not st.session_state.crawl_running:
    parsed = urlparse(url_input)
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        st.error("Please enter a full URL starting with https:// (e.g. https://example.com)")
    else:
        domain = parsed.netloc.lstrip("www.")
        try:
            _redis = redis.from_url(REDIS_URL, decode_responses=True)
            qm_check = QueueManager(domain, redis_client=_redis)
            if qm_check.has_existing_state():
                st.session_state.pending_resume = {
                    "url": url_input, "domain": domain,
                    "max_pages": max_pages, "rate_limit": rate_limit,
                }
            else:
                st.session_state.pending_resume = None
                _start_crawl(url_input, int(max_pages), rate_limit)
        except Exception:
            _start_crawl(url_input, int(max_pages), rate_limit)

# --- Resume prompt ---
if st.session_state.pending_resume:
    pr = st.session_state.pending_resume
    st.info(f"Existing crawl found for **{pr['domain']}**. Resume or start fresh?")
    col_a, col_b = st.columns(2)
    if col_a.button("Resume"):
        _start_crawl(pr["url"], pr["max_pages"], pr["rate_limit"])
        st.session_state.pending_resume = None
    if col_b.button("Start Fresh"):
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        QueueManager(pr["domain"], redis_client=_redis).flush()
        _start_crawl(pr["url"], pr["max_pages"], pr["rate_limit"])
        st.session_state.pending_resume = None

# --- Live crawl polling ---
if st.session_state.crawl_running and st.session_state.result_queue:
    if st.button("Cancel"):
        st.session_state.cancel_flag.append(True)

    rq = st.session_state.result_queue
    batch = 0
    while batch < 10:
        try:
            result = rq.get_nowait()
            if result is None:
                st.session_state.crawl_running = False
                _build_zip()
                break
            st.session_state.results.append(result)
            _update_stats(result)
            _append_log(result)
            batch += 1
        except queue.Empty:
            break

    if st.session_state.crawl_running:
        time.sleep(0.3)
        st.rerun()

# --- Stats bar ---
s = st.session_state.stats
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Scraped", s["scraped"])
c2.metric("Failed", s["failed"])
c3.metric("Skipped", s["skipped"])
c4.metric("Words", f"{s['words']:,}")
c5.metric("Crawl4AI", s["crawl4ai"])
c6.metric("Scrapy fallback", s["scrapy"])

# --- Live feed ---
if st.session_state.log_lines:
    st.subheader("Live Feed")
    st.code("\n".join(st.session_state.log_lines), language=None)

# --- Download button ---
if st.session_state.zip_bytes:
    st.success(f"Crawl complete. {s['scraped']} pages scraped, {s['words']:,} words.")
    st.download_button(
        label="Download .zip",
        data=st.session_state.zip_bytes,
        file_name=f"{st.session_state.domain}-scraped.zip",
        mime="application/zip",
    )
