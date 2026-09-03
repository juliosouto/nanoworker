import pytest
from unittest.mock import MagicMock, patch

from agent.llm_providers import (
    call_gemini_llm,
    call_qwen_llm,
    call_groq_llm,
    call_openai_llm,
    call_ollama_llm,
    call_openrouter_llm
)

@pytest.fixture
def mock_cursor():
    return MagicMock()

def test_call_gemini_llm_no_api_key():
    with pytest.raises(ValueError, match="API Key for Gemini model is not set"):
        call_gemini_llm("model", [], {}, "content", MagicMock(), "sess", "msg", "tbl")

@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_success(mock_client_cls, mock_cursor):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat
    
    mock_response = MagicMock()
    mock_response.function_calls = []
    mock_response.text = "Gemini Response"
    mock_chat.send_message.return_value = mock_response
    
    res = call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    assert res == "Gemini Response"

@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_503_retry(mock_client_cls, mock_cursor):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat
    
    # First 503, then success
    mock_response = MagicMock()
    mock_response.function_calls = []
    mock_response.text = "Success after 503"
    
    mock_chat.send_message.side_effect = [Exception("503 Service Unavailable"), mock_response]
    
    with patch('time.sleep', return_value=None):
        res = call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    
    assert res == "Success after 503"

@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_400_error(mock_client_cls, mock_cursor):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat
    
    mock_chat.send_message.side_effect = Exception("400 Bad Request")
    
    with pytest.raises(Exception, match="400 Bad Request"):
        call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")

@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_tool_call(mock_client_cls, mock_cursor):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat
    
    # First response: tool call
    mock_fc = MagicMock()
    mock_fc.name = "dummy_tool"
    mock_fc.args = {"arg1": "val1"}
    
    mock_resp1 = MagicMock()
    mock_resp1.function_calls = [mock_fc]
    
    # Second response: text
    mock_resp2 = MagicMock()
    mock_resp2.function_calls = []
    mock_resp2.text = "Final Tool Response"
    
    mock_chat.send_message.side_effect = [mock_resp1, mock_resp2]
    
    def dummy_tool(arg1):
        return f"Tool ran with {arg1}"
    
    res = call_gemini_llm("model", [], {"tools": [dummy_tool]}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key", on_complete=MagicMock())
    assert res == "Final Tool Response"

@patch('agent.llm_providers.get_config')
@patch('google.genai.Client')
def test_call_gemini_llm_intercept(mock_client_cls, mock_get_config, mock_cursor):
    # Mock get_config to return autonomous mode 1
    def mock_get_config_side_effect(key, default=None):
        if key == "AUTONOMOUS_MODE":
            return "1"
        if key == "agent_name":
            return "TestAgent"
        return default
    mock_get_config.side_effect = mock_get_config_side_effect

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat
    
    # First response: tool call
    mock_fc = MagicMock()
    mock_fc.name = "dummy_tool"
    mock_fc.args = {"arg1": "val1"}
    
    mock_resp1 = MagicMock()
    mock_resp1.function_calls = [mock_fc]
    
    # Second response: text
    mock_resp2 = MagicMock()
    mock_resp2.function_calls = []
    mock_resp2.text = "Done after Gemini intercept!"
    
    mock_chat.send_message.side_effect = [mock_resp1, mock_resp2]
    
    def dummy_tool(arg1):
        return f"Tool ran with {arg1}"
    
    res = call_gemini_llm("model", [], {"tools": [dummy_tool]}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key", on_complete=MagicMock())
    
    assert res == "Done after Gemini intercept!"
    assert mock_chat.send_message.call_count == 2
    
    # Verify second send_message call includes the injected continue message
    last_call_args = mock_chat.send_message.call_args_list[-1][0][0]
    # last_call_args should be a list containing the tool response and the continue message
    assert len(last_call_args) == 2
    assert last_call_args[1].text == "TestAgent continue"

@patch('agent.llm_providers.get_config')
@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_429_waits_until_next_minute_and_resumes(mock_client_cls, mock_get_config, mock_cursor):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429 = ("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
               "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, "
               "limit: 250000, model: gemini-3.1-flash-lite. "
               "Please retry in 10.143389936s. "
               "'quotaId': 'GenerateContentInputTokensPerModelPerMinute-FreeTier'")

    mock_response = MagicMock()
    mock_response.function_calls = []
    mock_response.text = "Success after quota wait"
    mock_chat.send_message.side_effect = [Exception(err_429), mock_response]

    with patch('time.sleep', return_value=None) as mock_sleep, \
         patch('time.time', return_value=42.5):
        res = call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")

    assert res == "Success after quota wait"
    assert mock_chat.send_message.call_count == 2
    # 60 - 42.5 + 3 = 20.5s (significantly larger than the 10.14s provider retryDelay)
    mock_sleep.assert_called_once_with(20.5)

@patch('agent.llm_providers.get_config')
@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_429_sends_realtime_feedback(mock_client_cls, mock_get_config, mock_cursor):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429 = "429 RESOURCE_EXHAUSTED. Quota exceeded GenerateContentInputTokensPerModelPerMinute-FreeTier"

    mock_response = MagicMock()
    mock_response.function_calls = []
    mock_response.text = "Success after quota wait"
    mock_chat.send_message.side_effect = [Exception(err_429), mock_response]

    on_complete = MagicMock()

    with patch('time.sleep', return_value=None), \
         patch('time.time', return_value=30.0):
        res = call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl",
                              api_key="test_key", on_complete=on_complete)

    assert res == "Success after quota wait"
    feedbacks = [c[0][0] for c in on_complete.call_args_list]
    assert any("Quota exceeded (429)" in f for f in feedbacks)

@patch('agent.llm_providers.get_config')
@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_429_mid_tool_loop_resumes_from_failure(mock_client_cls, mock_get_config, mock_cursor):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429 = "429 RESOURCE_EXHAUSTED. Quota exceeded GenerateContentInputTokensPerModelPerMinute-FreeTier"

    mock_fc = MagicMock()
    mock_fc.name = "dummy_tool"
    mock_fc.args = {"arg1": "val1"}

    mock_resp_tool = MagicMock()
    mock_resp_tool.function_calls = [mock_fc]

    mock_resp_final = MagicMock()
    mock_resp_final.function_calls = []
    mock_resp_final.text = "Final after tool and quota"

    mock_chat.send_message.side_effect = [mock_resp_tool, Exception(err_429), mock_resp_final]

    def dummy_tool(arg1):
        return f"Tool ran with {arg1}"

    with patch('time.sleep', return_value=None), \
         patch('time.time', return_value=59.9):
        res = call_gemini_llm("model", [], {"tools": [dummy_tool]}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key", on_complete=MagicMock())

    assert res == "Final after tool and quota"
    # tool exec -> send -> quota 429 -> send -> final text: send_message called 3 times
    assert mock_chat.send_message.call_count == 3
    # Last call carries only the tool response (retry resumed from the same point, no duplicated tool runs)
    last_call_args = mock_chat.send_message.call_args_list[-1][0][0]
    assert len(last_call_args) == 1

@patch('agent.llm_providers.get_config')
@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_429_exhausts_retries_raises(mock_client_cls, mock_get_config, mock_cursor):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429 = "429 RESOURCE_EXHAUSTED. Quota exceeded GenerateContentInputTokensPerModelPerMinute-FreeTier"

    mock_chat.send_message.side_effect = Exception(err_429)

    with patch('time.sleep', return_value=None) as mock_sleep, \
         patch('time.time', return_value=30.0), \
         pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
        call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")

    # 5 attempts, only the first 4 wait (last attempt must re-raise for fallback)
    assert mock_sleep.call_count == 4

@patch('agent.llm_providers.get_config')
@patch('agent.llm_providers.genai.Client')
def test_call_gemini_llm_429_daily_quota_raises_immediately(mock_client_cls, mock_get_config, mock_cursor):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429_daily = "429 RESOURCE_EXHAUSTED. Quota exceeded GenerateContentInputTokensPerModelPerDay-FreeTier"

    mock_chat.send_message.side_effect = Exception(err_429_daily)

    with patch('time.sleep', return_value=None) as mock_sleep, \
         pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
        call_gemini_llm("model", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")

    mock_sleep.assert_not_called()

def test_call_qwen_llm_no_api_key():
    with pytest.raises(ValueError, match="API Key for Qwen"):
        call_qwen_llm("model", [], {}, "content", MagicMock(), "sess", "msg", "tbl")

@patch('agent.llm_providers.execute_openai_compatible_llm')
@patch('openai.OpenAI')
def test_call_qwen_llm_success(mock_openai, mock_execute, mock_cursor):
    mock_execute.return_value = "Qwen Response"
    res = call_qwen_llm("qwen-max", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    assert res == "Qwen Response"
    mock_execute.assert_called_once()

def test_call_groq_llm_no_api_key():
    with pytest.raises(ValueError, match="API Key for Groq"):
        call_groq_llm("model", [], {}, "content", MagicMock(), "sess", "msg", "tbl")

@patch('agent.llm_providers.execute_openai_compatible_llm')
@patch('groq.Groq')
def test_call_groq_llm_success(mock_groq, mock_execute, mock_cursor):
    mock_execute.return_value = "Groq Response"
    res = call_groq_llm("llama", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    assert res == "Groq Response"
    mock_execute.assert_called_once()

def test_call_openai_llm_no_api_key():
    with pytest.raises(ValueError, match="API Key for OpenAI"):
        call_openai_llm("model", [], {}, "content", MagicMock(), "sess", "msg", "tbl")

@patch('agent.llm_providers.execute_openai_compatible_llm')
@patch('openai.OpenAI')
def test_call_openai_llm_success(mock_openai, mock_execute, mock_cursor):
    mock_execute.return_value = "OpenAI Response"
    res = call_openai_llm("gpt-4", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    assert res == "OpenAI Response"
    mock_execute.assert_called_once()

@patch('agent.llm_providers.execute_openai_compatible_llm')
@patch('openai.OpenAI')
def test_call_ollama_llm_success(mock_openai, mock_execute, mock_cursor):
    mock_execute.return_value = "Ollama Response"
    res = call_ollama_llm("ollama/llama", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl")
    assert res == "Ollama Response"
    # Ensure prefix was stripped
    args, kwargs = mock_execute.call_args
    assert args[1] == "llama"

def test_call_openrouter_llm_no_api_key():
    with pytest.raises(ValueError, match="API Key for OpenRouter"):
        call_openrouter_llm("model", [], {}, "content", MagicMock(), "sess", "msg", "tbl")

@patch('agent.llm_providers.execute_openai_compatible_llm')
@patch('openai.OpenAI')
def test_call_openrouter_llm_success(mock_openai, mock_execute, mock_cursor):
    mock_execute.return_value = "OpenRouter Response"
    res = call_openrouter_llm("openrouter/llama", [], {}, "Hello", mock_cursor, "sess", "msg", "tbl", api_key="test_key")
    assert res == "OpenRouter Response"
    args, kwargs = mock_execute.call_args
    assert args[1] == "llama"
