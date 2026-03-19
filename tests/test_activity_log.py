from activity_log import (
    ActivityLogStore,
    activity_marker_changed,
    ensure_activity_state,
    log_activity,
)


def test_activity_log_store_appends_and_lists_entries(tmp_path):
    store = ActivityLogStore(path=tmp_path / "activity_log.json")
    store.append_entry({"source": "crawl", "message": "Started crawl"})
    store.append_entry({"source": "index", "message": "Completed indexing", "level": "success"})

    entries = store.list_entries()

    assert len(entries) == 2
    assert entries[0]["message"] == "Completed indexing"
    assert entries[1]["message"] == "Started crawl"


def test_activity_log_store_clear_removes_entries(tmp_path):
    store = ActivityLogStore(path=tmp_path / "activity_log.json")
    store.append_entry({"source": "crawl", "message": "Started crawl"})

    store.clear()

    assert store.list_entries() == []


def test_activity_marker_changed_tracks_transitions():
    session_state = {}
    ensure_activity_state(session_state)

    assert activity_marker_changed(session_state, "crawl:job-1:status", "discovering") is True
    assert activity_marker_changed(session_state, "crawl:job-1:status", "discovering") is False
    assert activity_marker_changed(session_state, "crawl:job-1:status", "crawling") is True


def test_log_activity_writes_to_store_and_session_state(tmp_path):
    store = ActivityLogStore(path=tmp_path / "activity_log.json")
    session_state = {}

    entry = log_activity(
        session_state,
        "models",
        "Pulled Ollama models",
        level="success",
        details="Endpoint: http://ollama:11434",
        store=store,
    )

    assert entry["source"] == "models"
    assert entry["level"] == "success"
    assert session_state["activity_last_entry"]["message"] == "Pulled Ollama models"
    assert store.list_entries()[0]["details"] == "Endpoint: http://ollama:11434"
