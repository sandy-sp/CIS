# pages/settings_page.py
"""Settings page: configure API keys, model selection, and endpoints."""
import streamlit as st

from activity_log import log_activity
from app_settings import (
    SettingsStore,
    default_ollama_url,
    embedding_model_defaults,
    ensure_session_settings,
    llm_model_defaults,
)
from chat.generator import Generator
from indexer.embedder import Embedder
from ollama_status import get_ollama_status, pull_ollama_models


_LLM_BACKENDS = ["ollama", "openai", "anthropic"]
_LLM_BACKEND_LABELS = {
    "ollama": "Bundled Ollama",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
}
_EMBEDDING_BACKENDS = ["ollama", "openai", "local"]
_EMBEDDING_BACKEND_LABELS = {
    "ollama": "Bundled Ollama",
    "openai": "OpenAI API",
    "local": "Advanced local model",
}
_SETTINGS_STORE = SettingsStore()


def _show_check_result(result: dict) -> None:
    st.success(result["message"])
    details = [f"Backend: {result['backend']}", f"Model: {result['model']}"]
    if "dimensions" in result:
        details.append(f"Dimensions: {result['dimensions']}")
    st.caption(" | ".join(details))


def _render_ollama_status_panel(
    backend: str,
    llm_model: str,
    embedding_backend: str,
    embedding_model: str,
    ollama_url: str,
) -> None:
    local_chat_model = llm_model if backend == "ollama" else llm_model_defaults()["ollama"]
    local_embedding_model = (
        embedding_model if embedding_backend == "ollama" else embedding_model_defaults()["ollama"]
    )
    status_key = (ollama_url, local_chat_model, local_embedding_model)

    st.subheader("Bundled Ollama Status")
    st.caption("Checks the bundled Ollama server and the local models used for Docker chat and embeddings.")
    pull_notice = st.session_state.pop("ollama_pull_notice", "")
    if pull_notice:
        st.success(pull_notice)
    pull_errors = st.session_state.pop("ollama_pull_errors", {})
    for model, error in pull_errors.items():
        st.error(f"Failed to pull `{model}`: {error}")
    refresh = st.button("Refresh Ollama Status")
    if refresh or st.session_state.get("ollama_status_key") != status_key:
        with st.spinner("Checking Ollama status..."):
            st.session_state.ollama_status = get_ollama_status(
                ollama_url=ollama_url,
                chat_model=local_chat_model,
                embedding_model=local_embedding_model,
            )
            st.session_state.ollama_status_key = status_key

    status = st.session_state.get("ollama_status", {})
    if not status:
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Server", "Reachable" if status.get("reachable") else "Unavailable")
    c2.metric("Installed models", status.get("installed_count", 0))
    c3.metric("Bundled chat", "Ready" if status.get("ready_for_chat") else "Missing model")
    c4.metric("Bundled embeddings", "Ready" if status.get("ready_for_indexing") else "Missing model")

    if status.get("error"):
        st.error(f"Ollama check failed: {status['error']}")
    elif status.get("reachable"):
        st.success(f"Ollama is reachable at `{status['ollama_url']}`.")

    rows = [
        {
            "Role": "Chat",
            "Model": status.get("chat_model", ""),
            "Installed": "Yes" if status.get("chat_model_available") else "No",
            "Checked Against": "Current Ollama selection" if backend == "ollama" else "Docker default local model",
        },
        {
            "Role": "Embedding",
            "Model": status.get("embedding_model", ""),
            "Installed": "Yes" if status.get("embedding_model_available") else "No",
            "Checked Against": (
                "Current Ollama selection" if embedding_backend == "ollama" else "Docker default local model"
            ),
        },
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    installed_models = status.get("installed_models", [])
    if installed_models:
        st.caption(f"Installed models: {', '.join(installed_models)}")
    else:
        st.caption("Installed models: none detected yet.")

    missing_models = []
    if not status.get("chat_model_available") and status.get("chat_model"):
        missing_models.append(status["chat_model"])
    if not status.get("embedding_model_available") and status.get("embedding_model"):
        missing_models.append(status["embedding_model"])
    missing_models = sorted(set(missing_models))

    if status.get("reachable") and missing_models:
        st.caption(f"Missing models: {', '.join(missing_models)}")
        if st.button("Pull Missing Ollama Models"):
            log_activity(
                st.session_state,
                "models",
                f"Pulling Ollama models: {', '.join(missing_models)}",
                details=f"Endpoint: {ollama_url}",
            )
            with st.spinner("Pulling missing Ollama models..."):
                result = pull_ollama_models(ollama_url=ollama_url, models=missing_models)
            with st.spinner("Refreshing Ollama status..."):
                st.session_state.ollama_status = get_ollama_status(
                    ollama_url=ollama_url,
                    chat_model=local_chat_model,
                    embedding_model=local_embedding_model,
                )
                st.session_state.ollama_status_key = status_key
            if result.get("pulled_models"):
                log_activity(
                    st.session_state,
                    "models",
                    f"Pulled Ollama models: {', '.join(result['pulled_models'])}",
                    level="success",
                    details=f"Endpoint: {ollama_url}",
                )
            if result.get("failed_models"):
                for model, error in result["failed_models"].items():
                    log_activity(
                        st.session_state,
                        "models",
                        f"Failed to pull Ollama model `{model}`",
                        level="error",
                        details=error,
                    )
            st.session_state.ollama_pull_notice = (
                f"Pulled models: {', '.join(result['pulled_models'])}"
                if result.get("pulled_models")
                else ""
            )
            st.session_state.ollama_pull_errors = result.get("failed_models", {})
            st.rerun()
    elif status.get("reachable"):
        st.caption("All checked Ollama models are already installed.")


def settings_page() -> None:
    st.title("Settings")
    st.caption("Choose the models used for indexing and chat. The default Docker path uses bundled Ollama for both.")
    st.caption("Saved locally in `data/app_settings.json` on this machine.")

    # --- Load current settings ---
    s = ensure_session_settings(st.session_state, store=_SETTINGS_STORE)
    saved_llm_backend = s.get("llm_backend", "ollama")
    saved_embedding_backend = s.get("embedding_backend", "ollama")
    default_llm_models = llm_model_defaults()
    default_embedding_models = embedding_model_defaults()

    st.subheader("LLM Settings")
    backend = st.selectbox(
        "LLM Backend",
        _LLM_BACKENDS,
        index=_LLM_BACKENDS.index(s.get("llm_backend", "ollama")),
        format_func=lambda key: _LLM_BACKEND_LABELS[key],
    )

    api_key = ""
    if backend == "openai":
        api_key = st.text_input("OpenAI API Key", value=s.get("api_key", ""),
                                type="password", placeholder="sk-...")
    elif backend == "anthropic":
        api_key = st.text_input("Anthropic API Key", value=s.get("api_key", ""),
                                type="password", placeholder="sk-ant-...")

    llm_model = st.text_input(
        "LLM Model",
        value=(s.get("llm_model") if saved_llm_backend == backend else "") or default_llm_models[backend],
        help="Examples: qwen3:4b-instruct, qwen2.5:3b, gpt-4o-mini, claude-haiku-4-5",
    )

    ollama_url = st.text_input(
        "Ollama Endpoint",
        value=s.get("ollama_url", default_ollama_url()),
        help="URL of your local Ollama server",
    )

    if st.button("Test LLM Connection"):
        try:
            with st.spinner("Testing LLM connection..."):
                result = Generator(
                    backend=backend,
                    api_key=api_key,
                    model=llm_model,
                    ollama_url=ollama_url,
                ).health_check()
            _show_check_result(result)
        except Exception as exc:
            st.error(f"LLM connection failed: {exc}")

    st.subheader("Embedding Settings")
    embedding_backend = st.selectbox(
        "Embedding Backend",
        _EMBEDDING_BACKENDS,
        index=_EMBEDDING_BACKENDS.index(s.get("embedding_backend", "ollama")),
        format_func=lambda key: _EMBEDDING_BACKEND_LABELS[key],
    )

    embedding_api_key = ""
    if embedding_backend == "openai":
        embedding_api_key = st.text_input(
            "OpenAI Embedding API Key",
            value=s.get("embedding_api_key", ""),
            type="password",
            placeholder="sk-...",
        )

    embedding_model = st.text_input(
        "Embedding Model",
        value=(s.get("embedding_model") if saved_embedding_backend == embedding_backend else "") or default_embedding_models[embedding_backend],
        help="Examples: BAAI/bge-m3, nomic-embed-text, text-embedding-3-small",
    )
    if embedding_backend == "local":
        st.caption("Advanced option. Local sentence-transformers models are optional and not included in the default Docker image.")

    if st.button("Test Embedding Connection"):
        try:
            with st.spinner("Testing embedding connection..."):
                result = Embedder(
                    backend=embedding_backend,
                    api_key=embedding_api_key,
                    model=embedding_model,
                    ollama_url=ollama_url,
                ).health_check()
            _show_check_result(result)
        except Exception as exc:
            st.error(f"Embedding connection failed: {exc}")

    _render_ollama_status_panel(
        backend=backend,
        llm_model=llm_model,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        ollama_url=ollama_url,
    )

    if st.button("Save Settings", type="primary"):
        saved_settings = _SETTINGS_STORE.save({
            "llm_backend": backend,
            "api_key": api_key,
            "llm_model": llm_model,
            "ollama_url": ollama_url,
            "embedding_backend": embedding_backend,
            "embedding_api_key": embedding_api_key,
            "embedding_model": embedding_model,
        })
        st.session_state.settings = saved_settings
        st.success("Settings saved locally.")
