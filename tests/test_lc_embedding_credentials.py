"""Embedding provider resolution: the default is local (LangChain
HuggingFaceEmbeddings on this machine, no API key); cloud providers are used
only when explicitly selected, with the key the app already stores."""
import importlib

import pytest

import database
from database import encrypt_value, init_db, set_config


def _real_embeddings_module():
    """Reloads agent.lc.embeddings so the real get_embeddings is back (the
    conftest autouse fixture replaces it with a fake)."""
    import agent.lc.embeddings as e

    return importlib.reload(e)


@pytest.fixture
def ready_db(monkeypatch):
    init_db()
    monkeypatch.delenv("LC_EMBEDDINGS_PROVIDER", raising=False)
    return database


def _add_llm_row(provider, api_key):
    conn = database.get_db()
    conn.execute(
        "INSERT INTO llm_config (model_name, provider, api_key) VALUES (?, ?, ?)",
        (f"{provider}-model", provider, encrypt_value(api_key) if api_key else None),
    )
    conn.commit()
    conn.close()


def test_default_provider_is_local_even_with_cloud_keys(ready_db):
    _add_llm_row("gemini", "AIza-test-key")
    _add_llm_row("openai", "sk-test")
    e = _real_embeddings_module()
    assert e.get_embeddings_provider() == "local"


def test_local_model_is_all_minilm(ready_db):
    e = _real_embeddings_module()
    assert e.embeddings_model("local") == "all-MiniLM-L6-v2"


def test_explicit_cloud_provider_uses_stored_key(ready_db):
    _add_llm_row("gemini", "AIza-test-key")
    set_config("LC_EMBEDDINGS_PROVIDER", "gemini")
    e = _real_embeddings_module()
    assert e.get_embeddings_provider() == "gemini"
    assert e._embedding_api_key("gemini") == "AIza-test-key"


def test_gemini_falls_back_to_app_config_key(ready_db):
    set_config("GEMINI_API_KEY", "AIza-config-key")
    e = _real_embeddings_module()
    assert e._embedding_api_key("gemini") == "AIza-config-key"


def test_openai_key_only_from_openai_row(ready_db):
    _add_llm_row("qwen", "qwen-key")
    e = _real_embeddings_module()
    assert e._embedding_api_key("openai") is None
    _add_llm_row("openai", "sk-test")
    assert e._embedding_api_key("openai") == "sk-test"


def test_get_embeddings_local_uses_huggingface_embeddings(ready_db, monkeypatch):
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    calls = {}

    class FakeHF:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(e, "_embedding_class_by_provider", lambda provider: FakeHF)
    assert isinstance(e.get_embeddings(), FakeHF)
    assert calls == {"model_name": "all-MiniLM-L6-v2", "cache_folder": e.LOCAL_CACHE_DIR}


def test_get_embeddings_cloud_builds_client_with_stored_key(ready_db, monkeypatch):
    _add_llm_row("gemini", "AIza-test-key")
    set_config("LC_EMBEDDINGS_PROVIDER", "gemini")
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(e, "_embedding_class_by_provider", lambda provider: FakeClient)
    assert isinstance(e.get_embeddings(), FakeClient)
    assert calls["google_api_key"] == "AIza-test-key"
    assert calls["model"] == "models/text-embedding-004"


def test_get_embeddings_cloud_returns_none_without_key(ready_db, monkeypatch):
    set_config("LC_EMBEDDINGS_PROVIDER", "openai")
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    monkeypatch.setattr(e, "_embedding_class_by_provider", lambda provider: pytest.fail("no client expected"))
    assert e.get_embeddings() is None
    assert e.embeddings_available() is False


def test_local_embeddings_are_384_dim_and_normalised(ready_db):
    """Runs the real all-MiniLM-L6-v2 model; skipped when its weights are not
    cached and the environment has no network to fetch them."""
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    try:
        model = e._embedding_class_by_provider("local")(
            model_name=e.LOCAL_MODEL, cache_folder=e.LOCAL_CACHE_DIR
        )
    except Exception as exc:
        pytest.skip(f"local embedding model not available: {exc}")
    vec = model.embed_query("Bom dia pessoal")
    assert len(vec) == 384
    docs = model.embed_documents(["Bom dia", "Vamos jogar futebol"])
    assert len(docs) == 2 and all(len(d) == 384 for d in docs)
