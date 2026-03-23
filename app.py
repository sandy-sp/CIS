# app.py — multi-page entry point
import streamlit as st

from activity_log import ActivityLogStore, ensure_activity_state
from app_settings import ensure_session_settings
from pages.scrape_page import scrape_page
from pages.index_page import index_page
from pages.chat_page import chat_page
from pages.settings_page import settings_page
from runtime_badges import build_runtime_badges


_ACTIVITY_LOG = ActivityLogStore()


def _render_runtime_badges() -> None:
    badges = build_runtime_badges(st.session_state.get("settings", {}))
    cols = st.columns(len(badges))
    for col, badge in zip(cols, badges):
        with col:
            st.caption(badge["label"])
            st.markdown(f"`{badge['value']}`")


def _render_activity_log() -> None:
    with st.expander("Activity Log", expanded=False):
        actions = st.columns([1, 4])
        if actions[0].button("Clear Log", key="clear_activity_log"):
            _ACTIVITY_LOG.clear()
            st.rerun()
        actions[1].caption("Recent crawl, review, benchmark, indexing, model, and chat events.")

        entries = _ACTIVITY_LOG.list_entries(limit=30)
        if not entries:
            st.caption("No activity recorded yet.")
            return

        rows = []
        for entry in entries:
            rows.append({
                "Time": entry.get("timestamp", "")[:19].replace("T", " "),
                "Area": entry.get("source", ""),
                "Level": entry.get("level", ""),
                "Event": entry.get("message", ""),
                "Details": entry.get("details", ""),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Company Intelligence Workspace", layout="wide")
    ensure_session_settings(st.session_state)
    ensure_activity_state(st.session_state)

    pages = {
        "Scrape": scrape_page,
        "Index": index_page,
        "Chat": chat_page,
        "Settings": settings_page,
    }

    page = st.sidebar.radio("Workspace", list(pages.keys()))
    _render_runtime_badges()
    _render_activity_log()
    pages[page]()


if __name__ == "__main__":
    main()
