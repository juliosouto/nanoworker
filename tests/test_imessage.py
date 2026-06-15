import pytest
import subprocess
import os
import sqlite3
from unittest.mock import patch, MagicMock

from tools.macos import imessage

def test_send_imessage_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_run.return_value = mock_result
    
    res = imessage.send_imessage("1234567890", "Hello")
    assert "Message sent successfully" in res

def test_send_imessage_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_run.side_effect = subprocess.CalledProcessError(1, "osascript", stderr="Failed")
    
    res = imessage.send_imessage("1234567890", "Hello")
    assert "Error sending iMessage: Failed" in res

def test_send_imessage_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System Crash"))
    res = imessage.send_imessage("1234567890", "Hello")
    assert "Error sending iMessage: System Crash" in res

def test_read_recent_imessages_db_not_found(mocker):
    mocker.patch('os.path.exists', return_value=False)
    res = imessage.read_recent_imessages()
    assert "chat.db not found" in res[0]["error"]

def test_read_recent_imessages_success(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mock_connect = mocker.patch('sqlite3.connect')
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    mock_row1 = {"rowid": 1, "text": "Hi", "is_from_me": 0, "sender_id": "1234"}
    mock_row2 = {"rowid": 2, "text": "Hello", "is_from_me": 1, "sender_id": None}
    mock_cursor.fetchall.return_value = [mock_row1, mock_row2]
    
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    res = imessage.read_recent_imessages()
    assert len(res) == 2
    # Returned in reverse order
    assert res[0]["text"] == "Hello"
    assert res[0]["sender"] == "Me"
    assert res[1]["text"] == "Hi"
    assert res[1]["sender"] == "1234"

def test_read_recent_imessages_permission_error(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('sqlite3.connect', side_effect=sqlite3.OperationalError("operation not permitted"))
    res = imessage.read_recent_imessages()
    assert "Operation not permitted" in res[0]["error"]

def test_read_recent_imessages_other_db_error(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('sqlite3.connect', side_effect=sqlite3.OperationalError("database is locked"))
    res = imessage.read_recent_imessages()
    assert "Database error: database is locked" in res[0]["error"]

def test_read_recent_imessages_exception(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('sqlite3.connect', side_effect=Exception("Unknown"))
    res = imessage.read_recent_imessages()
    assert "Unexpected error: Unknown" in res[0]["error"]
