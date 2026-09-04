import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner


class TestNvidiaRouting(unittest.TestCase):
    @patch('database.get_db')
    @patch('agent.llm_providers.call_nvidia_llm')
    @patch('database.decrypt_value')
    def test_routing_to_nvidia(self, mock_decrypt, mock_call_nvidia, mock_get_db):
        # Setup mock db and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Row mock returning nvidia as provider
        mock_cursor.fetchone.return_value = {
            'provider': 'nvidia',
            'api_key': 'encrypted_api_key',
            'thinking': 0,
            'context_window': None,
            'max_output_tokens': None,
        }
        mock_decrypt.return_value = 'decrypted_api_key'

        history = []
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'

        agent_runner.route_llm_call(
            'nvidia/poolside/laguna-xs-2.1', history, config_kwargs, content,
            cursor, session_id, message_in_id, is_ide=False)

        mock_call_nvidia.assert_called_once_with(
            'nvidia/poolside/laguna-xs-2.1',
            history,
            config_kwargs,
            content,
            cursor,
            session_id,
            message_in_id,
            'messages_out',
            'decrypted_api_key',
            None,
            on_complete=None
        )

    @patch('database.get_db')
    @patch('agent.llm_providers.call_nvidia_llm')
    @patch('agent.llm_providers.call_qwen_llm')
    @patch('database.decrypt_value')
    def test_nvidia_takes_precedence_over_qwen_prefix(self, mock_decrypt, mock_call_qwen, mock_call_nvidia, mock_get_db):
        # A NIM-hosted Qwen model must route to NVIDIA, not to DashScope/qwen.
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            'provider': 'nvidia',
            'api_key': 'encrypted_api_key',
            'thinking': 0,
            'context_window': None,
            'max_output_tokens': None,
        }
        mock_decrypt.return_value = 'decrypted_api_key'

        agent_runner.route_llm_call(
            'nvidia/qwen/qwen3-next-80b-a3b-instruct', [], {}, 'test',
            MagicMock(), 'session-123', 'msg-123', is_ide=False)

        mock_call_nvidia.assert_called_once()
        mock_call_qwen.assert_not_called()

    @patch('database.get_db')
    @patch('agent.llm_providers.call_nvidia_llm')
    @patch('database.decrypt_value')
    def test_nvidia_prefix_without_db_row(self, mock_decrypt, mock_call_nvidia, mock_get_db):
        # Model not registered in llm_config still routes via the "nvidia/" prefix.
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        agent_runner.route_llm_call(
            'nvidia/meta/llama-3.3-70b-instruct', [], {}, 'test',
            MagicMock(), 'session-123', 'msg-123', is_ide=False)

        mock_call_nvidia.assert_called_once()


if __name__ == '__main__':
    unittest.main()