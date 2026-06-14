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
