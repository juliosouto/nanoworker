import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner
from google.genai import types

class TestOpenAIRouting(unittest.TestCase):
    @patch('database.get_db')
    @patch('agent_runner.call_openai_llm')
    @patch('database.decrypt_value')
    def test_routing_to_openai(self, mock_decrypt, mock_call_openai, mock_get_db):
        # Setup mock db and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Row mock returning openai as provider
        mock_cursor.fetchone.return_value = {
            'provider': 'openai',
            'api_key': 'encrypted_api_key',
            'thinking': 0,
            'max_output_tokens': 2048
        }
        mock_decrypt.return_value = 'decrypted_api_key'
        
        # Define mock arguments
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        # Invoke route_llm_call
        agent_runner.route_llm_call('gpt-4o', history, config_kwargs, content, cursor, session_id, message_in_id, is_ide=False)
        
        # Check call_openai_llm is invoked
        mock_call_openai.assert_called_once_with(
            'gpt-4o',
            history,
            config_kwargs,
            content,
            cursor,
            session_id,
            message_in_id,
            'messages_out',
            'decrypted_api_key',
            2048
        )

    @patch('openai.OpenAI')
    def test_openai_reasoning_parameter_adaptation(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_completion = MagicMock()
        mock_client.chat.completions.create.return_value = [mock_completion]
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].delta.content = "reasoning response"
        
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        # Test with o1-mini reasoning model name (starts with openai/o1-mini)
        res = agent_runner.call_openai_llm(
            'openai/o1-mini', history, config_kwargs, content, cursor, session_id, message_in_id, 'messages_out', 'api_key', 2048
        )
        
        self.assertEqual(res, "reasoning response")
        mock_client.chat.completions.create.assert_called_once()
        kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertIsNone(kwargs.get('temperature'))
        self.assertEqual(kwargs.get('max_completion_tokens'), 2048)
        self.assertIsNone(kwargs.get('max_tokens'))

    @patch('openai.OpenAI')
    def test_openai_fallback_on_unsupported_max_tokens(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].delta.content = "fallback response"
        
        # Make the first call fail with a BadRequestError
        import openai
        def side_effect(*args, **kwargs):
            if kwargs.get('max_tokens') is not None:
                raise openai.BadRequestError("Unsupported parameter: 'max_tokens'", response=MagicMock(), body={})
            return [mock_completion]
            
        mock_client.chat.completions.create.side_effect = side_effect
        
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        # Test with gpt-5-reasoning (should trigger the catch and retry without max_tokens)
        res = agent_runner.call_openai_llm(
            'gpt-5-reasoning', history, config_kwargs, content, cursor, session_id, message_in_id, 'messages_out', 'api_key', 2048
        )
        
        self.assertEqual(res, "fallback response")
        self.assertEqual(mock_client.chat.completions.create.call_count, 2)
        
        # Verify the second call parameters
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1][1]
        self.assertIsNone(second_call_kwargs.get('temperature'))
        self.assertIsNone(second_call_kwargs.get('max_tokens'))
        self.assertEqual(second_call_kwargs.get('max_completion_tokens'), 2048)

    @patch('openai.OpenAI')
    def test_openai_no_tokens_by_default(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_completion = MagicMock()
        mock_client.chat.completions.create.return_value = [mock_completion]
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].delta.content = "default response"
        
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        # Call without max_output_tokens (None)
        agent_runner.call_openai_llm(
            'gpt-4o', history, config_kwargs, content, cursor, session_id, message_in_id, 'messages_out', 'api_key', None
        )
        
        mock_client.chat.completions.create.assert_called_once()
        kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertIsNone(kwargs.get('max_tokens'))
        self.assertIsNone(kwargs.get('max_completion_tokens'))
        self.assertEqual(kwargs.get('temperature'), 1.0)

if __name__ == '__main__':
    unittest.main()
