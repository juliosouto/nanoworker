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
def mock_db_path(monkeypatch, tmp_path):
    """
    Use a temporary database file for tests to prevent modifying the real DB.
    Since database.py uses DB_PATH, we monkeypatch it.
    """
    test_db = tmp_path / "test_nanoworker.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db))
    # Note: we may need to initialize the db schema if the tests require it
    return str(test_db)
