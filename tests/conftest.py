import pytest
import os
import sys

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app
import database

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    # We might want to set testing config here
    flask_app.config.update({
        "TESTING": True,
    })
    
    yield flask_app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()


@pytest.fixture(autouse=True)
def _embeddings_isolation(monkeypatch):
    """
    Isolate RAG/embedding code from real API keys and the module-level cache.

    Every process-level ``get_embeddings`` / ``embeddings_available`` call
    returns an 8-dim ``FakeEmbeddings``. This prevents accidental real API
    calls (which would cost money / hit rate limits) and avoids polluting the
    cache with a provider resolved from the production ``llm_config`` table.
    Individual tests may re-patch for their own scenarios.
    """
    from langchain_core.embeddings import FakeEmbeddings

    import agent.lc.memory_rag as m
    import agent.lc.embeddings as e

    def fn():
        return FakeEmbeddings(size=8, seed=42)

    monkeypatch.setattr(m, "get_embeddings", fn)
    monkeypatch.setattr(e, "get_embeddings", fn)
    monkeypatch.setattr(m, "embeddings_available", lambda: True)
    monkeypatch.setattr(e, "embeddings_available", lambda: True)

@pytest.fixture(autouse=True)
def mock_db_path(monkeypatch, tmp_path):
    """
    Use a temporary database file for tests to prevent modifying the real DB.
    Since database.py uses DB_PATH, we monkeypatch it.
    """
    test_db = tmp_path / "test_nanoworker.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db))
    # Note: we may need to initialize the db schema if the tests require it
    return str(test_db)


@pytest.fixture(autouse=True)
def legacy_stack_for_tests(monkeypatch):
    """
    Pin LLM_STACK=legacy unless a test overrides it.

    Since Fase 6 the production default is 'langchain', but the vast majority
    of this suite was written against the legacy provider loops (routing,
    pruning, prompt building, tool loops). Without this pin, route_llm_call
    would silently dispatch those tests into the LangChain runner and fire
    REAL provider requests. Tests that exercise the langchain default itself
    (e.g. test_lc_tokens::test_stack_default_is_langchain) delete/override
    this env var explicitly; tests that patch lc_settings.stack_enabled are
    unaffected either way.
    """
    monkeypatch.setenv("LLM_STACK", "legacy")
