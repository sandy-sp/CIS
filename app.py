import streamlit as st

from pages.jobs_page import jobs_page
from pages.scrape_page import scrape_page, sync_active_crawl_state


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
            max-width: 1100px;
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


def _apply_pending_navigation(state, pages: dict[str, object]) -> None:
    target = str(state.pop("next_page", "") or "").strip()
    if target in pages:
        state["current_page"] = target


def main() -> None:
    st.set_page_config(
        page_title="Company Intelligence Scraper",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_app_styles()
    sync_active_crawl_state(st.session_state)

    pages = {
        "Scrape": scrape_page,
        "Jobs": jobs_page,
    }
    if "current_page" not in st.session_state:
        st.session_state.current_page = "Scrape"
    _apply_pending_navigation(st.session_state, pages)

    with st.sidebar:
        st.caption("Workspace")
        page = st.radio(
            "Workspace",
            list(pages.keys()),
            key="current_page",
            label_visibility="collapsed",
        )

    pages[page]()


if __name__ == "__main__":
    main()
