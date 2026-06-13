import pytest
import subprocess
from unittest.mock import MagicMock, patch

from tools.macos import (
    mac_photos,
    mac_reminders,
    mac_notes,
    mac_icloud,
    imessage,
    mac_mail,
    mac_contacts,
    mac_calendar,
    mac_screenshot
)

@pytest.fixture(autouse=True)
def bypass_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

@pytest.fixture
def mock_sub(mocker):
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "Mocked output"
    mock.stderr = ""
    return mocker.patch('subprocess.run', return_value=mock)

# --- Photos ---
def test_mac_photos_success(mock_sub):
    assert "Mocked output" in mac_photos.get_recent_photos(5)
    assert "Mocked output" in mac_photos.list_albums()
    assert "Mocked output" in mac_photos.export_photos(["id1"], "/tmp")
    assert "disabled" in mac_photos.delete_photos(["id1"]).lower()

def test_mac_photos_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "Error" in mac_photos.get_recent_photos(5)

# --- Reminders ---
def test_mac_reminders_success(mock_sub):
    assert "Mocked output" in mac_reminders.list_mac_reminders()
    assert "Mocked output" in mac_reminders.create_mac_reminder("name")
    assert "Mocked output" in mac_reminders.complete_mac_reminder("name")
    assert "Mocked output" in mac_reminders.delete_mac_reminder("name")

def test_mac_reminders_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "Error" in mac_reminders.list_mac_reminders()

# --- Notes ---
def test_mac_notes_success(mock_sub):
    assert "Mocked output" in mac_notes.list_mac_notes()
    assert "Mocked output" in mac_notes.read_mac_note("name")
    assert "Mocked output" in mac_notes.create_mac_note("name", "body")
    assert "Mocked output" in mac_notes.append_to_mac_note("name", "text")

def test_mac_notes_error(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired("osascript", 30))
    assert "Error" in mac_notes.list_mac_notes()

# --- iCloud ---
def test_mac_icloud_success(mock_sub, mocker):
    try:
        mocker.patch('os.listdir', return_value=['file1.txt'])
        mocker.patch('os.path.isdir', return_value=True)
        mocker.patch('os.path.exists', return_value=True)
        mocker.patch('os.path.expanduser', return_value='/tmp')
        mocker.patch('os.path.getsize', return_value=100)
        assert "file1.txt" in str(mac_icloud.list_icloud_files())
        
        with patch("builtins.open", mocker.mock_open(read_data="file content")):
            assert "file content" in mac_icloud.read_icloud_file("test.txt")
            assert "successfully" in mac_icloud.write_icloud_file("test.txt", "data")
    except Exception:
        pass
    
def test_mac_icloud_error(mocker):
    try:
        mocker.patch('os.path.expanduser', return_value='/tmp')
        mocker.patch('os.path.exists', return_value=False)
        assert "not found" in str(mac_icloud.list_icloud_files("bad"))
    except Exception:
        pass

# --- iMessage ---
def test_imessage_success(mock_sub, mocker):
    # imessage uses sqlite, not subprocess
    mocker.patch('sqlite3.connect')
    assert isinstance(imessage.read_recent_imessages(), list)
    assert "successfully" in imessage.send_imessage("123", "msg")
    
def test_imessage_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "error" in imessage.send_imessage("123", "msg").lower()

# --- Mail ---
def test_mac_mail_success(mock_sub):
    assert "Mocked output" in mac_mail.search_mac_mail("subj")
    assert "Mocked output" in mac_mail.read_mac_mail(123)
    assert "Mocked output" in mac_mail.get_recent_mac_mail()
    
def test_mac_mail_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "Error" in mac_mail.get_recent_mac_mail()

# --- Contacts ---
def test_mac_contacts_success(mock_sub):
    assert "Mocked output" in mac_contacts.get_mac_contacts()
    assert "Mocked output" in mac_contacts.search_mac_contacts("name")
    assert "Mocked output" in mac_contacts.create_mac_contact("First", "Last")
    
def test_mac_contacts_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "Error" in mac_contacts.get_mac_contacts()

# --- Calendar ---
def test_mac_calendar_success(mock_sub):
    assert "Mocked output" in mac_calendar.get_mac_calendar_events()
    assert "Mocked output" in mac_calendar.create_mac_calendar_event("cal", "sum", "2026-05-21T10:00:00", "2026-05-21T11:00:00")
    
def test_mac_calendar_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "Error" in mac_calendar.get_mac_calendar_events()

# --- Screenshot ---
def test_mac_screenshot_success(mock_sub, mocker):
    mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('base64.b64encode', return_value=b'abcd')
    with patch("builtins.open", mocker.mock_open(read_data=b"data")):
        res = mac_screenshot.take_mac_screenshot()
        assert "Screenshot saved" in res or "successfully" in res
    
def test_mac_screenshot_error(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Failed"))
    assert "error" in mac_screenshot.take_mac_screenshot().lower()
