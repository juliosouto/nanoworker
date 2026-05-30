import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner
from google.genai import types

# Simple dummy tools for testing signature parsing
def dummy_tool(path: str, content: str = "") -> str:
    """
    This is a dummy tool for testing.
    
    Args:
        path: The path parameter.
        content: The optional content parameter.
    """
    return f"Success {path} {content}"

class TestToolCalling(unittest.TestCase):
    def test_convert_to_openai_tool(self):
        openai_tool = agent_runner.convert_to_openai_tool(dummy_tool)
        
        self.assertEqual(openai_tool["type"], "function")
        func_schema = openai_tool["function"]
        self.assertEqual(func_schema["name"], "dummy_tool")
        self.assertEqual(func_schema["description"], "This is a dummy tool for testing.")
        
        props = func_schema["parameters"]["properties"]
        self.assertIn("path", props)
        self.assertEqual(props["path"]["type"], "string")
        self.assertEqual(props["path"]["description"], "The path parameter.")
        
        self.assertIn("content", props)
        self.assertEqual(props["content"]["type"], "string")
        self.assertEqual(props["content"]["description"], "The optional content parameter.")
        
        self.assertIn("path", func_schema["parameters"]["required"])
        self.assertNotIn("content", func_schema["parameters"]["required"])

    @patch('agent_runner.get_permitted_tools')
    def test_execute_openai_compatible_llm_loop(self, mock_get_permitted_tools):
        # Setup tools
        mock_get_permitted_tools.return_value = [dummy_tool]
        
        mock_client = MagicMock()
        mock_completion_1 = MagicMock()
        mock_completion_2 = MagicMock()
        
        # Mock the first response requesting a tool call
        mock_message_1 = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc123"
        mock_tool_call.function.name = "dummy_tool"
        mock_tool_call.function.arguments = '{"path": "my_file.txt", "content": "my content"}'
        
        mock_message_1.content = None
        mock_message_1.tool_calls = [mock_tool_call]
        mock_completion_1.choices = [MagicMock(message=mock_message_1)]
        
        # Mock the second response returning the final text answer
        mock_message_2 = MagicMock()
        mock_message_2.content = "Final Task Completed!"
        mock_message_2.tool_calls = None
        mock_completion_2.choices = [MagicMock(message=mock_message_2)]
        
        # Side effect to return tool call first, then text response
        mock_client.chat.completions.create.side_effect = [mock_completion_1, mock_completion_2]
        
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {"tools": True}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        res = agent_runner.execute_openai_compatible_llm(
            mock_client, 'gpt-4o', history, config_kwargs, content, cursor, session_id, message_in_id, 'messages_out'
        )
        
        self.assertEqual(res, "Final Task Completed!")
        self.assertEqual(mock_client.chat.completions.create.call_count, 2)
        
        # Verify call history update
        # Since 'messages' is mutated in-place, both recorded calls hold a reference to the same list object
        # which eventually contains 4 messages at the end of the loop execution.
        final_messages = mock_client.chat.completions.create.call_args_list[1][1]["messages"]
        self.assertEqual(len(final_messages), 4)
        self.assertEqual(final_messages[0]["role"], "user")
        self.assertEqual(final_messages[1]["role"], "user")
        self.assertEqual(final_messages[2]["role"], "assistant")
        self.assertEqual(final_messages[3]["role"], "tool")
        self.assertEqual(final_messages[3]["content"], "Success my_file.txt my content")

if __name__ == '__main__':
    unittest.main()
