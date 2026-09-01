import pytest
from unittest.mock import patch, MagicMock
import requests

from tools.linux import whatsapp as linux_wa
from tools.macos import whatsapp as macos_wa
from tools.windows import whatsapp as windows_wa

@pytest.fixture(params=[
    ("linux", linux_wa),
    ("macos", macos_wa),
    ("windows", windows_wa)
])
def wa_setup(request):
    return request.param

def setup_db_mock(mocker, allowed_to="5511999999999", allow_mentions=False):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {
        "allowed_to": allowed_to,
        "allow_mentions": allow_mentions
    }
    mocker.patch('database.get_db', return_value=mock_conn)
    return mock_conn

def test_is_allowed_to_self(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._is_allowed_to("self") is True

def test_is_allowed_to_allowed(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')  # ignore /me call
    assert wa_module._is_allowed_to("5511999999999") is True

def test_is_allowed_to_denied(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    assert wa_module._is_allowed_to("123456789") is False

def test_send_whatsapp_message_success(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    # Mock audio extraction
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("5511999999999", "Hello")
    assert "successfully" in res

def test_send_whatsapp_message_denied(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    res = wa_module.send_whatsapp_message("123456789", "Hello")
    assert "Access Denied" in res

def test_send_whatsapp_message_audio_and_text(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="12036312345-123@g.us")
    mocker.patch('requests.get')
    
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", "/tmp/audio.ogg"))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("12036312345-123@g.us", "Hello")
    assert "successfully" in res

def test_send_whatsapp_message_503(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("5511999999999", "Hello")
    assert "not connected" in res

def test_send_whatsapp_message_timeout(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    mocker.patch('requests.post', side_effect=requests.exceptions.Timeout)
    
    res = wa_module.send_whatsapp_message("5511999999999", "Hello")
    assert "timed out" in res

def test_send_whatsapp_file_success(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.remove')
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/copy.pdf")
    mocker.patch('mimetypes.guess_type', return_value=('application/pdf', None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"target": "5511999999999"}
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_file("5511999999999", "/fake/file.pdf", "Here is your file")
    assert "successfully" in res

def test_send_whatsapp_file_denied(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999", allow_mentions=False)
    mocker.patch('requests.get')
    
    res = wa_module.send_whatsapp_file("123456789", "/fake/file.pdf")
    assert "Access Denied" in res

def test_send_whatsapp_file_not_found(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="5511999999999")
    mocker.patch('requests.get')
    
    mocker.patch('os.path.isfile', return_value=False)
    
    res = wa_module.send_whatsapp_file("5511999999999", "/fake/file.pdf")
    assert "File not found" in res

def test_is_allowed_to_no_config(wa_setup, mocker):
    os_name, wa_module = wa_setup
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    mocker.patch('database.get_db', return_value=mock_conn)
    assert wa_module._is_allowed_to("123456") is True

def test_is_allowed_to_allow_mentions_override(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="", allow_mentions=True)
    assert wa_module._is_allowed_to("123456", allow_mentions_override=True) is True

def test_is_allowed_to_empty_allowed_to(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="", allow_mentions=False)
    mocker.patch('requests.get', side_effect=Exception("mock"))
    assert wa_module._is_allowed_to("123456") is False

def test_is_allowed_to_db_exception(wa_setup, mocker):
    os_name, wa_module = wa_setup
    mocker.patch('database.get_db', side_effect=Exception("DB Error"))
    assert wa_module._is_allowed_to("123456") is True

def test_is_allowed_to_own_number(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"number": "123456"}
    mocker.patch('requests.get', return_value=mock_resp)
    
    assert wa_module._is_allowed_to("123456") is True

def test_is_allowed_to_lid_number(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"lid_number": "654321"}
    mocker.patch('requests.get', return_value=mock_resp)
    
    assert wa_module._is_allowed_to("654321") is True

def test_send_whatsapp_message_group_jid(wa_setup, mocker):
    os_name, wa_module = wa_setup
    mocker.patch.object(wa_module, '_is_allowed_to', return_value=True)
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", "/tmp/audio.ogg"))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("12036312345-123", "Hello")
    assert "successfully" in res

def test_send_whatsapp_message_http_error(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Bad Request"
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("1234", "Hello")
    assert "HTTP 400" in res

def test_send_whatsapp_message_audio_503(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=(None, "/tmp/audio.ogg"))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("1234", "")
    assert "WhatsApp client is not connected" in res

def test_send_whatsapp_message_audio_http_error(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=(None, "/tmp/audio.ogg"))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_message("1234", "")
    assert "HTTP 400" in res

def test_send_whatsapp_message_connection_error(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    import requests
    mocker.patch('requests.post', side_effect=requests.exceptions.ConnectionError("conn err"))
    
    res = wa_module.send_whatsapp_message("1234", "Hello")
    assert "Could not connect to WhatsApp service" in res

def test_send_whatsapp_message_exception(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))
    
    mocker.patch('requests.post', side_effect=Exception("Unknown"))
    
    res = wa_module.send_whatsapp_message("1234", "Hello")
    assert "Error sending WhatsApp message: Unknown" in res

def test_send_whatsapp_file_copy_exception(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('utils.file_utils.create_temp_copy', side_effect=Exception("copy fail"))
    
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "Error copying file to temporary directory: copy fail" in res

def test_send_whatsapp_file_no_mimetype(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.remove')
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/unknown.bin")
    mocker.patch('mimetypes.guess_type', return_value=(None, None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"target": "1234"}
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_file("1234", "/fake/unknown.bin")
    assert "successfully" in res

def test_send_whatsapp_file_group_jid(wa_setup, mocker):
    os_name, wa_module = wa_setup
    mocker.patch.object(wa_module, '_is_allowed_to', return_value=True)
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.remove')
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/file.pdf")
    mocker.patch('mimetypes.guess_type', return_value=('application/pdf', None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"target": "12036312345-123@g.us"}
    mocker.patch('requests.post', return_value=mock_resp)
    
    res = wa_module.send_whatsapp_file("12036312345-123", "/fake/file.pdf")
    assert "successfully" in res

def test_send_whatsapp_file_errors(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.remove')
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/file.pdf")
    mocker.patch('mimetypes.guess_type', return_value=('application/pdf', None))
    
    # 503 error
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mocker.patch('requests.post', return_value=mock_resp)
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "WhatsApp client is not connected" in res

    # HTTP Error
    mock_resp.status_code = 400
    mock_resp.text = "Bad Request"
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "HTTP 400 - Bad Request" in res

    # ConnectionError
    import requests
    mocker.patch('requests.post', side_effect=requests.exceptions.ConnectionError("conn err"))
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "Could not connect to WhatsApp service" in res

    # Timeout
    mocker.patch('requests.post', side_effect=requests.exceptions.Timeout("timeout err"))
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "WhatsApp service timed out" in res

    # General Exception
    mocker.patch('requests.post', side_effect=Exception("Unknown Error"))
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    assert "Error sending WhatsApp file: Unknown Error" in res

def test_send_whatsapp_file_remove_exception(wa_setup, mocker):
    os_name, wa_module = wa_setup
    setup_db_mock(mocker, allowed_to="1234")
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/file.pdf")
    mocker.patch('mimetypes.guess_type', return_value=('application/pdf', None))
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"target": "1234"}
    mocker.patch('requests.post', return_value=mock_resp)
    
    # Simulate os.remove throwing an exception
    mocker.patch('os.remove', side_effect=Exception("cannot delete"))
    
    res = wa_module.send_whatsapp_file("1234", "/fake/file.pdf")
    # Even if remove fails, the response is still success
    assert "successfully" in res
def test_format_jid_preserves_lid(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("5511999998888@lid") == "5511999998888@lid"

def test_format_jid_preserves_group_suffix(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("120363123456789@lid".replace("@lid", "@g.us")) == "120363123456789@g.us"

def test_format_jid_wa_web_prefix_lid(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("wa_web:5511999998888@lid") == "5511999998888@lid"

def test_format_jid_bare_group(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("12036312345-123") == "12036312345-123@g.us"

def test_format_jid_bare_number(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("5511999998888") == "5511999998888@s.whatsapp.net"

def test_format_jid_self_returns_none(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._format_jid("self") is None
    assert wa_module._format_jid("") is None

def test_jid_number_strips_suffix(wa_setup):
    os_name, wa_module = wa_setup
    assert wa_module._jid_number("5511999998888@lid") == "5511999998888"
    assert wa_module._jid_number("120363123456789@g.us") == "120363123456789"
    assert wa_module._jid_number("5511999998888:3@lid") == "5511999998888"

def test_send_whatsapp_message_self_no_unbound_error(wa_setup, mocker):
    """Regression: 'self' used to raise UnboundLocalError due to a mis-indented jid block."""
    os_name, wa_module = wa_setup
    mocker.patch.object(wa_module, '_is_allowed_to', return_value=True)
    mocker.patch('requests.get')
    mocker.patch('utils.audio_utils.extract_and_generate_audio', return_value=("Hello", None))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mocker.patch('requests.post', return_value=mock_resp)

    res = wa_module.send_whatsapp_message("self", "Hello")
    assert "successfully" in res

def test_send_whatsapp_file_lid_jid(wa_setup, mocker):
    """File sent to a private LID chat must preserve the @lid suffix."""
    os_name, wa_module = wa_setup
    mocker.patch.object(wa_module, '_is_allowed_to', return_value=True)
    mocker.patch('requests.get')
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.remove')
    mocker.patch('utils.file_utils.create_temp_copy', return_value="/tmp/copy.jpg")
    mocker.patch('mimetypes.guess_type', return_value=(None, None))

    captured = {}
    def fake_post(url, json=None, timeout=None, **kwargs):
        captured['payload'] = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"target": json.get("jid", "?")}
        return mock_resp
    mocker.patch('requests.post', side_effect=fake_post)

    res = wa_module.send_whatsapp_file("5511999998888@lid", "/fake/photo.jpg")
    assert "successfully" in res
    assert captured['payload']['jid'] == "5511999998888@lid"
    # unknown mimetype should fall back to image/jpeg because of the .jpg extension
    assert captured['payload']['mimetype'] == "image/jpeg"
