"""Scripted cron jobs: the script runs without the agent and its stdout is sent."""

from unittest.mock import MagicMock, patch

import pytest

import database
from database import get_db, set_config
from utils import cron_script
from utils.cron_script import run_cron_script


@pytest.fixture
def terminal_on(mock_db_path):
    database.init_db()
    set_config('PERM_TERMINAL', 'true')


def test_refused_when_terminal_permission_is_off(mock_db_path):
    database.init_db()
    set_config('PERM_TERMINAL', 'false')
    assert "PERM_TERMINAL" in run_cron_script("print('x')")


def test_stdout_is_returned(terminal_on):
    assert run_cron_script("print('oi')\nprint('tchau')") == "oi\ntchau"


def test_no_output_means_silent(terminal_on):
    assert run_cron_script("x = 1") == ""


def test_failure_reports_exit_code_and_error(terminal_on):
    out = run_cron_script("raise SystemExit(3)")
    assert "exit code 3" in out
    out = run_cron_script("1/0")
    assert "ZeroDivisionError" in out


def test_timeout(terminal_on, monkeypatch):
    monkeypatch.setattr(cron_script, 'SCRIPT_TIMEOUT_SECONDS', 1)
    assert "timed out" in run_cron_script("import time\ntime.sleep(5)")


def test_sweeper_sends_output_to_chat():
    from sweeper import run_script_job
    callback = MagicMock()
    with patch('utils.cron_script.run_cron_script', return_value="Apagada a mensagem."):
        run_script_job('job-1', 'print(1)', callback)
    callback.assert_called_once_with("Apagada a mensagem.")


def test_sweeper_stays_silent_on_empty_output():
    from sweeper import run_script_job
    callback = MagicMock()
    with patch('utils.cron_script.run_cron_script', return_value=""):
        run_script_job('job-1', 'print(1)', callback)
    callback.assert_not_called()


def test_api_stores_script_and_allows_script_without_prompt(mock_db_path):
    from app import app
    database.init_db()
    conn = get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s9', 'a1', 'grp@g.us')")
    conn.commit()
    conn.close()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        response = client.post('/api/cron', json={
            'session_id': 's9', 'description': 'Scripted', 'content': '',
            'script': 'print("hi")', 'cron_expression': '*/5 * * * *',
        })
        assert response.status_code == 201, response.get_json()
        job_id = response.get_json()['id']
        assert client.post('/api/cron', json={
            'session_id': 's9', 'description': 'Empty', 'content': '', 'cron_expression': '* * * * *',
        }).status_code == 400
    conn = get_db()
    row = conn.execute('SELECT script, content FROM cron_jobs WHERE id = ?', (job_id,)).fetchone()
    conn.close()
    assert row['script'] == 'print("hi")'
    assert row['content'] == ''
