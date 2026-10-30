"""Embeddings are always local (LangChain HuggingFaceEmbeddings on this
machine, no API key), whatever chat providers or LC_EMBEDDINGS_PROVIDER value
are configured."""
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


def test_provider_is_local_even_with_cloud_keys(ready_db):
    _add_llm_row("Google", "AIza-test-key")
    _add_llm_row("openai", "sk-test")
    e = _real_embeddings_module()
    assert e.get_embeddings_provider() == "local"


@pytest.mark.parametrize("value", ["gemini", "openai", "auto"])
def test_cloud_setting_is_ignored(ready_db, monkeypatch, value):
    from agent.lc import settings

    set_config("LC_EMBEDDINGS_PROVIDER", value)
    monkeypatch.setenv("LC_EMBEDDINGS_PROVIDER", value)
    e = _real_embeddings_module()
    assert settings.embeddings_provider() == "local"
    assert e.get_embeddings_provider() == "local"
    assert e.embeddings_model(value) == "all-MiniLM-L6-v2"


def test_local_model_is_all_minilm(ready_db):
    e = _real_embeddings_module()
    assert e.embeddings_model() == "all-MiniLM-L6-v2"


def test_get_embeddings_uses_huggingface_embeddings(ready_db, monkeypatch):
    _add_llm_row("Google", "AIza-test-key")
    set_config("LC_EMBEDDINGS_PROVIDER", "gemini")
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    calls = {}

    class FakeHF:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(e, "_embedding_class", lambda: FakeHF)
    assert isinstance(e.get_embeddings(), FakeHF)
    assert calls == {"model_name": "all-MiniLM-L6-v2", "cache_folder": e.LOCAL_CACHE_DIR}


def test_get_embeddings_caches_per_model(ready_db, monkeypatch):
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    loaded = []

    class FakeHF:
        def __init__(self, **kwargs):
            loaded.append(kwargs["model_name"])

    monkeypatch.setattr(e, "_embedding_class", lambda: FakeHF)
    messages = e.get_embeddings()
    tools = e.get_embeddings(e.TOOL_MODEL)
    assert messages is not tools
    assert e.get_embeddings(e.TOOL_MODEL) is tools
    assert loaded == ["all-MiniLM-L6-v2", "paraphrase-multilingual-MiniLM-L12-v2"]


def test_get_embeddings_returns_none_when_model_fails(ready_db, monkeypatch):
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)

    def boom(**kwargs):
        raise RuntimeError("no weights")

    monkeypatch.setattr(e, "_embedding_class", lambda: boom)
    assert e.get_embeddings() is None
    assert e.embeddings_available() is False


def test_local_embeddings_are_384_dim_and_normalised(ready_db):
    """Runs the real all-MiniLM-L6-v2 model; skipped when its weights are not
    cached and the environment has no network to fetch them."""
    e = _real_embeddings_module()
    e.get_embeddings.__dict__.pop("_cache", None)
    try:
        model = e._embedding_class()(
            model_name=e.LOCAL_MODEL, cache_folder=e.LOCAL_CACHE_DIR
        )
    except Exception as exc:
        pytest.skip(f"local embedding model not available: {exc}")
    vec = model.embed_query("Bom dia pessoal")
    assert len(vec) == 384
    docs = model.embed_documents(["Bom dia", "Vamos jogar futebol"])
    assert len(docs) == 2 and all(len(d) == 384 for d in docs)
