from app import _apply_pending_navigation


def test_apply_pending_navigation_updates_current_page():
    state = {
        "current_page": "Jobs",
        "next_page": "Scrape",
    }

    _apply_pending_navigation(state, {"Scrape": object(), "Jobs": object()})

    assert state["current_page"] == "Scrape"
    assert "next_page" not in state


def test_apply_pending_navigation_ignores_unknown_target():
    state = {
        "current_page": "Jobs",
        "next_page": "Settings",
    }

    _apply_pending_navigation(state, {"Scrape": object(), "Jobs": object()})

    assert state["current_page"] == "Jobs"
    assert "next_page" not in state
