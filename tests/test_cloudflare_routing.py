import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner


class TestCloudflareRouting(unittest.TestCase):
    """route_llm_call dispatches Cloudflare models to call_cloudflare_llm.

    Mirrors tests/test_nvidia_routing.py: the conftest pins LLM_STACK=legacy,
    so the legacy provider branches are exercised.
    """

    def _mock_db(self, mock_get_db, provider):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            'provider': provider,
            'api_key': 'encrypted_api_key',
            'thinking': 0,
            'context_window': None,
            'max_output_tokens': None,
        }
        return mock_cursor

    @patch('database.get_db')
    @patch('agent.llm_providers.call_cloudflare_llm')
    @patch('database.decrypt_value')
    def test_routing_to_cloudflare_by_provider_column(self, mock_decrypt, mock_call_cloudflare, mock_get_db):
        self._mock_db(mock_get_db, 'cloudflare')
        mock_decrypt.return_value = 'decrypted_api_key'

        history = []
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'

        agent_runner.route_llm_call(
            '@cf/qwen/qwen3.8-27b', history, config_kwargs, content,
            cursor, session_id, message_in_id, is_ide=False)

        mock_call_cloudflare.assert_called_once_with(
            '@cf/qwen/qwen3.8-27b',
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
    @patch('agent.llm_providers.call_cloudflare_llm')
    @patch('database.decrypt_value')
    def test_cloudflare_prefix_fallback_without_registration(self, mock_decrypt, mock_call_cloudflare, mock_get_db):
        # A model with no registered provider column is detected by the
        # "@cf/" prefix and still routes to Cloudflare.
        self._mock_db(mock_get_db, None)
        mock_decrypt.return_value = 'decrypted_api_key'

        agent_runner.route_llm_call(
            '@cf/meta/llama-3.3-70b-instruct-fp8-fast', [], {}, 'test',
            MagicMock(), 'session-123', 'msg-123', is_ide=False)

        assert mock_call_cloudflare.call_args[0][0] == '@cf/meta/llama-3.3-70b-instruct-fp8-fast'
        mock_call_cloudflare.assert_called_once()

    @patch('database.get_db')
    @patch('agent.llm_providers.call_qwen_llm')
    @patch('agent.llm_providers.call_cloudflare_llm')
    @patch('database.decrypt_value')
    def test_cloudflare_takes_precedence_over_qwen_prefix(self, mock_decrypt, mock_call_cloudflare, mock_call_qwen, mock_get_db):
        # A Cloudflare-hosted Qwen model must route to Cloudflare (Workers AI),
        # never to the DashScope/qwen branch, even though the name contains
        # "qwen".
        self._mock_db(mock_get_db, 'cloudflare')
        mock_decrypt.return_value = 'decrypted_api_key'

        agent_runner.route_llm_call(
            '@cf/qwen/qwen3.8-27b', [], {}, 'test',
            MagicMock(), 'session-123', 'msg-123', is_ide=False)

        mock_call_cloudflare.assert_called_once()
        mock_call_qwen.assert_not_called()

    @patch('database.get_db')
    @patch('agent.llm_providers.call_qwen_llm')
    @patch('agent.llm_providers.call_cloudflare_llm')
    @patch('database.decrypt_value')
    def test_hf_prefix_routes_to_cloudflare(self, mock_decrypt, mock_call_cloudflare, mock_call_qwen, mock_get_db):
        self._mock_db(mock_get_db, None)
        mock_decrypt.return_value = 'decrypted_api_key'

        agent_runner.route_llm_call(
            '@hf/thebloke/deepseek-coder-6.7b-instruct-awq', [], {}, 'test',
            MagicMock(), 'session-123', 'msg-123', is_ide=False)

        mock_call_cloudflare.assert_called_once()
        mock_call_qwen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
