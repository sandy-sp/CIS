import pytest
from datetime import datetime, timezone
from models import PageResult


@pytest.fixture
def sample_html():
    return """
    <html>
    <head>
        <title>Our Services</title>
        <meta name="description" content="We offer great services">
        <link rel="canonical" href="https://example.com/services">
    </head>
    <body>
        <nav>Nav links here</nav>
        <main>
            <h1>Our Services</h1>
            <h2>Consulting</h2>
            <p>We help businesses grow through strategic consulting.</p>
            <h2>Development</h2>
            <p>We build custom software solutions.</p>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """


@pytest.fixture
def sample_page_result():
    return PageResult(
        url="https://example.com/services",
        canonical_url="https://example.com/services",
        title="Our Services",
        description="We offer great services",
        language="en",
        raw_html="<h1>Our Services</h1><p>We help businesses grow.</p>",
        markdown="# Our Services\n\nWe help businesses grow.",
        page_type="services",
        word_count=6,
        scraped_at=datetime(2026, 3, 17, 10, 0, 0, tzinfo=timezone.utc),
        engine_used="crawl4ai",
        status="success",
    )
