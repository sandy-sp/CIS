from pages.scrape_page import _external_review_rows


def test_external_review_rows_extract_metadata():
    rows = _external_review_rows([
        {
            "url": "https://www.linkedin.com/company/example",
            "domain": "linkedin.com",
            "source_type": "external",
            "discovered_via": "search",
            "page_category": "external-profile",
            "status": "success",
            "metadata": {
                "review_score": 91,
                "review_status": "approved",
                "review_reason": "Search-discovered on linkedin.com | query type: company_profile | rank 1",
                "search_provider": "duckduckgo",
                "search_kind": "company_profile",
                "search_rank": 1,
                "search_query": 'site:linkedin.com/company "Example"',
            },
        },
        {
            "url": "https://example.com/about",
            "domain": "example.com",
            "source_type": "internal",
            "discovered_via": "crawl",
            "page_category": "company",
            "status": "success",
            "metadata": {},
        },
    ])

    assert len(rows) == 1
    assert rows[0]["Domain"] == "linkedin.com"
    assert rows[0]["Score"] == 91
    assert rows[0]["Review Status"] == "approved"
    assert rows[0]["Query Type"] == "company_profile"
