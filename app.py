# app.py — multi-page entry point
import streamlit as st

from pages.scrape_page import scrape_page
from pages.clean_page import clean_page
from pages.index_page import index_page
from pages.chat_page import chat_page


def main() -> None:
    st.set_page_config(page_title="Business RAG Pipeline", layout="wide")

    pages = {
        "Scrape": scrape_page,
        "Clean": clean_page,
        "Index": index_page,
        "Chat": chat_page,
    }

    page = st.sidebar.radio("Pipeline", list(pages.keys()))
    pages[page]()


if __name__ == "__main__":
    main()
