# app.py — multi-page entry point
import streamlit as st

from activity_log import ActivityLogStore, ensure_activity_state
from app_settings import ensure_session_settings
from pages.scrape_page import scrape_page, sync_active_crawl_state
from pages.index_page import index_page
from pages.chat_page import chat_page
from pages.settings_page import settings_page
from runtime_badges import build_runtime_badges


_ACTIVITY_LOG = ActivityLogStore()


def _inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {
            display: none;
        }
        [data-testid="stAppViewContainer"] .main .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1200px;
        }
        [data-testid="stSidebar"] .stRadio > div {
            gap: 0.25rem;
        }
        [data-testid="stSidebar"] .stRadio label {
            padding: 0.15rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_runtime_badges() -> None:
    badges = build_runtime_badges(st.session_state.get("settings", {}))
    for badge in badges:
        st.caption(badge["label"])
        st.markdown(f"`{badge['value']}`")


def _render_activity_log() -> None:
    with st.expander("Activity Log", expanded=False):
        actions = st.columns([1, 2])
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
    st.set_page_config(
        page_title="Company Intelligence Workspace",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ensure_session_settings(st.session_state)
    ensure_activity_state(st.session_state)
    sync_active_crawl_state(st.session_state)
    _inject_app_styles()

    pages = {
        "Scrape": scrape_page,
        "Index": index_page,
        "Chat": chat_page,
        "Settings": settings_page,
    }

    with st.sidebar:
        st.caption("Workspace")
        page = st.radio("Workspace", list(pages.keys()), label_visibility="collapsed")
        st.divider()
        st.caption("Runtime")
        _render_runtime_badges()
        _render_activity_log()

    st.session_state.current_page = page
    pages[page]()


if __name__ == "__main__":
    main()
