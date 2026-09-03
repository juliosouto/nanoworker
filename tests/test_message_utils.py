import pytest
from unittest.mock import patch, MagicMock

from utils.message_utils import (
    get_default_worker,
    resolve_worker_from_content,
    should_process_wa_message,
    clean_mention,
    truncate_message,
    check_rate_limit,
    format_dict_to_lines,
    format_document_search_results,
    process_tools_for_llm,
    resolve_target_jid,
    check_wa_permissions,
    apply_plan_before_execution
)

@pytest.fixture
def mock_db(mocker):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    mocker.patch('database.get_db', return_value=conn)
    return cursor

def test_get_default_worker_with_default(mock_db, mocker):

    mock_db.fetchall.return_value = [{'is_default': False}, {'is_default': True, 'worker_name': 'def'}]
    worker = get_default_worker()
    assert worker['worker_name'] == 'def'

def test_get_default_worker_fallback(mock_db, mocker):

    mock_db.fetchall.return_value = [{'is_default': False, 'worker_name': 'first'}]
    worker = get_default_worker()
    assert worker['worker_name'] == 'first'

def test_get_default_worker_empty(mock_db, mocker):

    mock_db.fetchall.return_value = []
    worker = get_default_worker()
    assert worker is None

def test_resolve_worker_from_content_text(mock_db, mocker):

    mock_db.fetchall.return_value = [{'is_default': False, 'worker_name': 'Nano'}]
    mocker.patch('database.get_config', return_value='false')
    worker = resolve_worker_from_content("@nano how are you?")
    assert worker['worker_name'] == 'Nano'

def test_resolve_worker_from_content_transcription(mock_db, mocker):

    mock_db.fetchall.return_value = [{'is_default': False, 'worker_name': 'Nano'}]
    mocker.patch('database.get_config', return_value='false')
    worker = resolve_worker_from_content("Audio message\n[Transcription]: nano do this")
    assert worker['worker_name'] == 'Nano'

def test_should_process_wa_message_bot_disabled(mock_db, mocker):

    mock_db.fetchone.return_value = {'bot_enabled': False}
    assert not should_process_wa_message('wa_web:me', 'user@s.whatsapp.net')

def test_should_process_wa_message_chat_with_self(mock_db, mocker):

    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '', 'allow_mentions': True}
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'number': '12345'}
    mocker.patch('requests.get', return_value=mock_resp)
    
    assert should_process_wa_message('12345@s.whatsapp.net', 'user')

def test_should_process_wa_message_not_allowed(mock_db, mocker):

    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '999', 'allow_mentions': True}
    mocker.patch('requests.get', side_effect=Exception)
    # Give it a worker name to pass the mention check if we mock DB
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')
    assert not should_process_wa_message('channel', '888@s.whatsapp.net', 'nano hello')

def test_clean_mention(mock_db, mocker):

    mock_db.fetchall.return_value = [{'worker_name': 'Nano'}]
    mocker.patch('database.get_config', return_value='false')
    
    cleaned = clean_mention("@nano please do this")
    assert cleaned == "please do this"
    
    cleaned_trans = clean_mention("Audio\n[Transcription]: nano please")
    assert cleaned_trans == "Audio\n[Transcription]: please"

def test_truncate_message(mocker):
    mocker.patch('database.get_config', return_value="5")
    # 5 tokens = 20 chars
    long_msg = "A" * 30
    assert len(truncate_message(long_msg)) == 20
    assert len(truncate_message("Short")) == 5

def test_check_rate_limit(mock_db, mocker):

    # Check rate limit returns no config
    mock_db.fetchone.return_value = None
    assert check_rate_limit('user')
    
    # Check rate limit exceeded
    mock_db.fetchone.side_effect = [{'rate_limit_per_minute': 2}, (2,)] # first fetchone is config, second is count
    assert not check_rate_limit('user2')

def test_format_dict_to_lines():
    d = {'a': 1, 'b': {'c': 2}, 'd': [3, 4]}
    lines = format_dict_to_lines(d)
    assert 'a: 1' in lines
    assert '  c: 2' in lines
    assert '  - 3' in lines

def test_format_document_search_results():
    results = [
        {"id": 1, "file_name": "test.txt", "extracted_data": {"key": "val"}, "metadata": {"meta": "data"}}
    ]
    fmt = format_document_search_results(results)
    assert "Document ID: 1" in fmt
    assert "key: val" in fmt
    assert "meta: data" in fmt

def test_process_tools_for_llm(mocker):
    mocker.patch('database.get_config', return_value="true")
    def my_tool():
        """My doc"""
        pass
    
    tools = [my_tool, "not_callable"]
    processed = process_tools_for_llm(tools)
    assert processed[0].__name__ == "my_tool"
    assert processed[0].__doc__ == "My doc"
    assert processed[1] == "not_callable"

def test_resolve_target_jid():
    assert resolve_target_jid({'remote_jid': '123'}) == '123'
    assert resolve_target_jid({'sender_id': '456'}) == '456@s.whatsapp.net'

def test_check_wa_permissions(mocker):
    mocker.patch('utils.message_utils.should_process_wa_message', return_value=(False, "audio_mentions_disabled"))
    allowed, reason = check_wa_permissions({'channel_id': 'wa_web:me', 'remote_jid': ''}, 'test')
    assert not allowed
    assert reason == "audio_mentions_disabled"

    # Reason falls back to the generic code when the checker returns an empty reason
    mocker.patch('utils.message_utils.should_process_wa_message', return_value=(False, None))
    allowed, reason = check_wa_permissions({'channel_id': 'wa_web:me', 'remote_jid': ''}, 'test')
    assert not allowed
    assert reason == "permissions_or_disabled"
    
    mocker.patch('utils.message_utils.should_process_wa_message', return_value=(True, None))
    mocker.patch('utils.message_utils.check_rate_limit', return_value=False)
    allowed, reason = check_wa_permissions({'channel_id': 'wa_web:me', 'remote_jid': ''}, 'test')
    assert not allowed
    assert reason == "rate_limit"
    
    mocker.patch('utils.message_utils.check_rate_limit', return_value=True)
    allowed, reason = check_wa_permissions({'channel_id': 'wa_web:me', 'remote_jid': ''}, 'test')
    assert allowed
    assert reason is None

def test_resolve_worker_from_content_no_content(mock_db):
    mock_db.fetchall.return_value = [{'is_default': True, 'worker_name': 'def'}]
    worker = resolve_worker_from_content("")
    assert worker['worker_name'] == 'def'

def test_resolve_worker_from_content_require_at(mock_db, mocker):
    mocker.patch('database.get_config', return_value='true') # require_at is True
    
    # Should fallback to default
    mock_db.fetchall.return_value = [{'is_default': True, 'worker_name': 'def'}, {'is_default': False, 'worker_name': 'Nano'}]
    worker = resolve_worker_from_content("nano how are you?")
    assert worker['worker_name'] == 'def'

def test_should_process_wa_message_no_config(mock_db):
    mock_db.fetchone.return_value = None
    assert should_process_wa_message('wa_web:me', 'user@s.whatsapp.net')

def test_should_process_wa_message_audio_mention(mock_db, mocker):
    # bot_enabled=True, allow_mentions=True, allow_audio_mentions=True
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '', 'allow_mentions': True, 'allow_audio_mentions': True}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')
    
    assert should_process_wa_message('channel', 'user@s.whatsapp.net', "Audio\n[Transcription]: nano hello")

def test_should_process_wa_message_exceptions_in_config(mock_db, mocker):
    # Mock KeyError for allow_mentions and allow_audio_mentions
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '*'}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')
    
    # Should still process if mentioned because allow_mentions defaults to True
    assert should_process_wa_message('channel', 'user@s.whatsapp.net', "@nano hello")

def test_should_process_wa_message_audio_disabled_reason(mock_db, mocker):
    # allow_audio_mentions = False + audio transcript -> reason "audio_mentions_disabled",
    # but default (bool) return must still be False.
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '*', 'allow_mentions': True, 'allow_audio_mentions': False}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')

    audio_content = "Audio\n[Transcription]: nano hello"
    assert should_process_wa_message('channel', 'user@s.whatsapp.net', audio_content) is False
    allowed, reason = should_process_wa_message('channel', 'user@s.whatsapp.net', audio_content, return_reason=True)
    assert allowed is False
    assert reason == "audio_mentions_disabled"

def test_should_process_wa_message_audio_no_mention_reason(mock_db, mocker):
    # allow_audio_mentions = True but transcription has no worker name
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '*', 'allow_mentions': True, 'allow_audio_mentions': True}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')

    audio_content = "Audio\n[Transcription]: hey do this please"
    allowed, reason = should_process_wa_message('channel', 'user@s.whatsapp.net', audio_content, return_reason=True)
    assert allowed is False
    assert reason == "no_worker_mentioned_in_transcription"

def test_should_process_wa_message_bot_disabled_reason(mock_db, mocker):
    mock_db.fetchone.return_value = {'bot_enabled': False}
    allowed, reason = should_process_wa_message('wa_web:me', 'user@s.whatsapp.net', return_reason=True)
    assert allowed is False
    assert reason == "bot_disabled"

def test_should_process_wa_message_sender_not_allowed_reason(mock_db, mocker):
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '999', 'allow_mentions': True}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')
    allowed, reason = should_process_wa_message('channel', '888@s.whatsapp.net', 'nano hello', return_reason=True)
    assert allowed is False
    assert reason == "sender_not_allowed"

def test_should_process_wa_message_allowed_reason_none(mock_db, mocker):
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '*'}
    mocker.patch('requests.get', side_effect=Exception)
    mock_db.fetchall.return_value = [{'worker_name': 'nano'}]
    mocker.patch('database.get_config', return_value='false')
    allowed, reason = should_process_wa_message('channel', 'user@s.whatsapp.net', '@nano hello', return_reason=True)
    assert allowed is True
    assert reason is None

def test_should_process_wa_message_chat_with_self_lid(mock_db, mocker):
    mock_db.fetchone.return_value = {'bot_enabled': True, 'allowed_from': '', 'allow_mentions': True}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'lid_number': '54321'}
    mocker.patch('requests.get', return_value=mock_resp)
    
    assert should_process_wa_message('54321@s.whatsapp.net', 'user')

def test_clean_mention_no_content():
    assert clean_mention("") == ""
    assert clean_mention(None) == ""

def test_truncate_message_exceptions(mocker):
    mocker.patch('database.get_config', side_effect=ValueError)
    long_msg = "A" * 1500
    # defaults to 250 tokens * 4 = 1000
    assert len(truncate_message(long_msg)) == 1000

def test_check_rate_limit_exceptions_and_logic(mock_db):
    # KeyError for limit
    mock_db.fetchone.return_value = {}
    assert check_rate_limit('user')
    
    # Limit <= 0
    mock_db.fetchone.return_value = {'rate_limit_per_minute': -1}
    assert check_rate_limit('user')

    # Successful insert
    mock_db.fetchone.side_effect = [{'rate_limit_per_minute': 10}, (5,)]
    assert check_rate_limit('user')

def test_format_dict_to_lines_edge_cases():
    d = {'a': [], 'b': {}}
    lines = format_dict_to_lines(d)
    assert len(lines) == 2
    
    # Passing a string directly
    lines2 = format_dict_to_lines("direct string")
    assert lines2 == ["direct string"]
    
    # Passing list of strings
    lines3 = format_dict_to_lines(["str1", "str2"])
    assert "- str1" in lines3

def test_format_document_search_results_not_list():
    assert format_document_search_results("not a list") == "not a list"

def test_process_tools_for_llm_empty_or_false(mocker):
    assert process_tools_for_llm([]) == []
    
    mocker.patch('database.get_config', return_value="false")
    def my_tool(): pass
    tools = [my_tool]
    assert process_tools_for_llm(tools) == tools


def test_apply_plan_before_execution_empty_or_disabled(mocker):
    # Empty / None content is returned unmodified regardless of the flag.
    mocker.patch('database.get_config', return_value="true")
    assert apply_plan_before_execution("") == ""
    assert apply_plan_before_execution(None) is None

    # Disabled -> content returned unmodified.
    mocker.patch('database.get_config', return_value="false")
    content = "hello world"
    assert apply_plan_before_execution(content) == content


def test_apply_plan_before_execution_enabled(mocker):
    mocker.patch('database.get_config', return_value="true")
    result = apply_plan_before_execution("please do this")

    assert result.startswith("[Plan Before Execution]")
    assert "Review the list of tools" in result
    assert "step-by-step plan" in result
    assert result.endswith("please do this")
