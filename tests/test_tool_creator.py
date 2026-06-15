import pytest
from unittest.mock import patch, MagicMock, mock_open

from tools.linux import tool_creator as linux_tc
from tools.macos import tool_creator as macos_tc
from tools.windows import tool_creator as windows_tc

@pytest.fixture(params=[linux_tc, macos_tc, windows_tc])
def tc_module(request):
    """Parameterize across OS versions of tool_creator.py."""
    return request.param

def test_create_tool_success(tc_module, mocker):
    mocker.patch('database.get_config', return_value='false')  # Disable double check
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=False)
    
    mock_file = mocker.patch('builtins.open', mock_open())
    
    mocker.patch('importlib.invalidate_caches')
    
    mock_module = MagicMock()
    mock_module.__name__ = "mock_module"
    mocker.patch('importlib.import_module', return_value=mock_module)
    mocker.patch('importlib.reload', return_value=mock_module)
    
    # Let's mock inspect.getmembers to return a fake function
    def fake_func(): pass
    fake_func.__module__ = "mock_module"
    fake_func.__name__ = "fake_func"
    
    mocker.patch('inspect.getmembers', return_value=[("fake_func", fake_func)])
    
    # We also need to mock sys.modules to avoid hot-reloading crashing
    mocker.patch('sys.modules', {})
    
    res = tc_module.create_self_developed_tool("my_new_tool", "def fake_func(): pass")
    
    assert "Successfully created self-developed tool 'my_new_tool'" in res
    assert mock_file.call_count >= 1

def test_create_tool_invalid_name(tc_module, mocker):
    mocker.patch('database.get_config', return_value='false')
    
    # Test spaces
    res = tc_module.create_self_developed_tool("invalid name", "code")
    assert "Error: tool_name must be a valid Python identifier" in res
    
    # Test reserved name
    res2 = tc_module.create_self_developed_tool("__init__", "code")
    assert "Error: Cannot name a tool '__init__'." in res2

def test_create_tool_exception(tc_module, mocker):
    mocker.patch('database.get_config', return_value='false')
    mocker.patch('os.makedirs', side_effect=PermissionError("Denied"))
    
    res = tc_module.create_self_developed_tool("my_tool", "code")
    assert "Error creating tool: Denied" in res

def test_create_tool_double_check_and_reload(tc_module, mocker):
    mocker.patch('database.get_config', side_effect=lambda k, d=None: 'true' if k == 'TOOL_CREATOR_DOUBLE_CHECK' else ('gemini-2.5-flash' if k == 'GEMINI_MODEL' else 'fake_enc_key'))
    mocker.patch('database.decrypt_value', return_value='fake_api_key')
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {'content': 'Prompt 1', 'created_at': '2023-01-02'},
        {'content': 'Prompt 2', 'created_at': '2023-01-01'}
    ]
    mock_db.cursor.return_value = mock_cursor
    mocker.patch('database.get_db', return_value=mock_db)
    
    mock_session = MagicMock()
    mock_session.get.return_value = 'sess-1'
    mocker.patch('utils.session.current_session_id', mock_session)
    
    mock_genai = mocker.patch('google.genai.Client')
    mock_chat = mock_genai.return_value.chats.create.return_value
    mock_chat.send_message.return_value.text = "```python\ndef fake_func(): pass\n```"
    
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=True)  # Pretend __init__ exists to cover that branch
    
    mock_file = mocker.patch('builtins.open', mock_open())
    
    mocker.patch('importlib.invalidate_caches')
    
    mock_module = MagicMock()
    mock_module.__name__ = "mock_module"
    
    def fake_func(): pass
    fake_func.__module__ = "mock_module"
    fake_func.__name__ = "fake_func"
    
    mocker.patch('inspect.getmembers', return_value=[("fake_func", fake_func)])
    mocker.patch('importlib.reload', return_value=mock_module)
    mocker.patch('importlib.import_module', return_value=mock_module)
    
    import sys
    sys_modules_mock = {
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}.my_tool": mock_module,
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}": mock_module
    }
    mocker.patch.dict(sys.modules, sys_modules_mock)
    
    mock_module.AVAILABLE_SELF_DEVELOPED_TOOLS = []
    
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    
    assert "Successfully created self-developed tool 'my_tool'" in res
    assert "validated by Thinking Mode" in res

def test_create_tool_double_check_prompt_cases(tc_module, mocker):
    mocker.patch('database.get_config', side_effect=lambda k, d=None: 'true' if k == 'TOOL_CREATOR_DOUBLE_CHECK' else ('gemini-2.5-flash' if k == 'GEMINI_MODEL' else 'fake_enc_key'))
    mocker.patch('database.decrypt_value', return_value='fake_api_key')
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    # Case 1: row1 < row2
    mock_cursor.fetchone.side_effect = [
        {'content': 'Prompt 1', 'created_at': '2023-01-01'},
        {'content': 'Prompt 2', 'created_at': '2023-01-02'}
    ]
    mock_db.cursor.return_value = mock_cursor
    mocker.patch('database.get_db', return_value=mock_db)
    
    mock_session = MagicMock()
    mock_session.get.return_value = 'sess-1'
    mocker.patch('utils.session.current_session_id', mock_session)
    
    mock_genai = mocker.patch('google.genai.Client')
    mock_chat = mock_genai.return_value.chats.create.return_value
    mock_chat.send_message.return_value.text = "```\ndef fake_func(): pass\n```"
    
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('builtins.open', mock_open())
    mocker.patch('importlib.invalidate_caches')
    
    mock_module = MagicMock()
    mock_module.__name__ = "mock_module"
    def fake_func(): pass
    fake_func.__module__ = "mock_module"
    fake_func.__name__ = "fake_func"
    mocker.patch('inspect.getmembers', return_value=[("fake_func", fake_func)])
    mocker.patch('importlib.reload', return_value=mock_module)
    mocker.patch('importlib.import_module', return_value=mock_module)
    import sys
    sys_modules_mock = {
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}.my_tool": mock_module,
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}": mock_module
    }
    mocker.patch.dict(sys.modules, sys_modules_mock)
    mock_module.AVAILABLE_SELF_DEVELOPED_TOOLS = []
    
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    assert "validated by Thinking Mode" in res

    # Case 2: only row1
    mock_cursor.fetchone.side_effect = [
        {'content': 'Prompt 1', 'created_at': '2023-01-01'},
        None
    ]
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    assert "validated by Thinking Mode" in res

    # Case 3: only row2
    mock_cursor.fetchone.side_effect = [
        None,
        {'content': 'Prompt 2', 'created_at': '2023-01-01'}
    ]
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    assert "validated by Thinking Mode" in res

def test_create_tool_double_check_no_api_key(tc_module, mocker):
    mocker.patch('database.get_config', side_effect=lambda k, d=None: 'true' if k == 'TOOL_CREATOR_DOUBLE_CHECK' else None)
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {'content': 'Prompt 1', 'created_at': '2023-01-01'},
        None
    ]
    mock_db.cursor.return_value = mock_cursor
    mocker.patch('database.get_db', return_value=mock_db)
    
    mock_session = MagicMock()
    mock_session.get.return_value = 'sess-1'
    mocker.patch('utils.session.current_session_id', mock_session)
    
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('builtins.open', mock_open())
    mocker.patch('importlib.invalidate_caches')
    
    mock_module = MagicMock()
    mock_module.__name__ = "mock_module"
    def fake_func(): pass
    fake_func.__module__ = "mock_module"
    fake_func.__name__ = "fake_func"
    mocker.patch('inspect.getmembers', return_value=[("fake_func", fake_func)])
    mocker.patch('importlib.reload', return_value=mock_module)
    mocker.patch('importlib.import_module', return_value=mock_module)
    import sys
    sys_modules_mock = {
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}.my_tool": mock_module,
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}": mock_module
    }
    mocker.patch.dict(sys.modules, sys_modules_mock)
    mock_module.AVAILABLE_SELF_DEVELOPED_TOOLS = []
    
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    assert "Successfully created self-developed tool" in res
    assert "validated by Thinking Mode" not in res

def test_create_tool_double_check_exception(tc_module, mocker):
    mocker.patch('database.get_config', side_effect=lambda k, d=None: 'true' if k == 'TOOL_CREATOR_DOUBLE_CHECK' else ('gemini-2.5-flash' if k == 'GEMINI_MODEL' else 'fake_enc_key'))
    mocker.patch('database.decrypt_value', side_effect=Exception("Decryption error"))
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {'content': 'Prompt 1', 'created_at': '2023-01-01'},
        None
    ]
    mock_db.cursor.return_value = mock_cursor
    mocker.patch('database.get_db', return_value=mock_db)
    
    mock_session = MagicMock()
    mock_session.get.return_value = 'sess-1'
    mocker.patch('utils.session.current_session_id', mock_session)
    
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('builtins.open', mock_open())
    mocker.patch('importlib.invalidate_caches')
    
    mock_module = MagicMock()
    mock_module.__name__ = "mock_module"
    def fake_func(): pass
    fake_func.__module__ = "mock_module"
    fake_func.__name__ = "fake_func"
    mocker.patch('inspect.getmembers', return_value=[("fake_func", fake_func)])
    mocker.patch('importlib.reload', return_value=mock_module)
    mocker.patch('importlib.import_module', return_value=mock_module)
    import sys
    sys_modules_mock = {
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}.my_tool": mock_module,
        f"tools.self-developed.{tc_module.__name__.split('.')[-2]}": mock_module
    }
    mocker.patch.dict(sys.modules, sys_modules_mock)
    mock_module.AVAILABLE_SELF_DEVELOPED_TOOLS = []
    
    res = tc_module.create_self_developed_tool("my_tool.py", "def wrong(): pass")
    assert "Successfully created self-developed tool" in res
    assert "validated by Thinking Mode" not in res

