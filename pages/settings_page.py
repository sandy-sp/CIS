# pages/settings_page.py
"""Settings page: configure API keys, model selection, and endpoints."""
import streamlit as st


_LLM_BACKENDS = ["ollama", "openai", "anthropic"]
_EMBEDDING_BACKENDS = ["local", "openai"]


def settings_page() -> None:
    st.title("Settings")
    st.caption("Configure API keys and model settings for the RAG pipeline.")

    # --- Load current settings ---
    if "settings" not in st.session_state:
        st.session_state.settings = {}

    s = st.session_state.settings

    st.subheader("LLM Settings")
    backend = st.selectbox(
        "LLM Backend",
        _LLM_BACKENDS,
        index=_LLM_BACKENDS.index(s.get("llm_backend", "ollama")),
    )

    api_key = ""
    if backend == "openai":
        api_key = st.text_input("OpenAI API Key", value=s.get("api_key", ""),
                                type="password", placeholder="sk-...")
    elif backend == "anthropic":
        api_key = st.text_input("Anthropic API Key", value=s.get("api_key", ""),
                                type="password", placeholder="sk-ant-...")

    ollama_url = st.text_input(
        "Ollama Endpoint",
        value=s.get("ollama_url", "http://localhost:11434"),
        help="URL of your local Ollama server",
    )

    st.subheader("Embedding Settings")
    embedding_backend = st.selectbox(
        "Embedding Backend",
        _EMBEDDING_BACKENDS,
        index=_EMBEDDING_BACKENDS.index(s.get("embedding_backend", "local")),
    )

    embedding_api_key = ""
    if embedding_backend == "openai":
        embedding_api_key = st.text_input(
            "OpenAI Embedding API Key",
            value=s.get("embedding_api_key", ""),
            type="password",
            placeholder="sk-...",
        )

    if st.button("Save Settings", type="primary"):
        st.session_state.settings = {
            "llm_backend": backend,
            "api_key": api_key,
            "ollama_url": ollama_url,
            "embedding_backend": embedding_backend,
            "embedding_api_key": embedding_api_key,
        }
        st.success("Settings saved!")
