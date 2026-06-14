import pytest
import os
import sys
import importlib
from unittest.mock import patch, MagicMock

def test_load_tools_from_directory_invalid():
    from tools import _load_tools_from_directory, AVAILABLE_TOOLS
    count = len(AVAILABLE_TOOLS)
    _load_tools_from_directory("/invalid/dir/that/does/not/exist/ever", "pkg")
    assert len(AVAILABLE_TOOLS) == count

def test_load_tools_from_directory_valid(tmp_path):
    # Create a temporary tool package
    pkg_dir = tmp_path / "dummy_tools"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "dummy_tool.py").write_text("""
def my_dummy_function():
    pass
def _private_function():
    pass
""")
    
    # Add tmp_path to sys.path so it can be imported
    sys.path.insert(0, str(tmp_path))
    
    from tools import _load_tools_from_directory, AVAILABLE_TOOLS
    initial_count = len(AVAILABLE_TOOLS)
    
    # Load from the dummy directory
    _load_tools_from_directory(str(pkg_dir), "dummy_tools")
    
    # Verify my_dummy_function was added
    found = False
    for tool in AVAILABLE_TOOLS:
        if tool.__name__ == "my_dummy_function":
            found = True
            break
            
    assert found is True
    
    # Verify private function was NOT added
    for tool in AVAILABLE_TOOLS:
        assert tool.__name__ != "_private_function"
        
    # Cleanup
    sys.path.pop(0)

@patch('tools.get_tool_config')
def test_get_permitted_tools_admin(mock_get_tool_config):
    from tools import get_permitted_tools
    mock_get_tool_config.return_value = {'enabled': True}
    
    tools = get_permitted_tools(is_admin=True)
    assert len(tools) > 0

@patch('tools.get_tool_config')
def test_get_permitted_tools_group(mock_get_tool_config):
    from tools import get_permitted_tools
    mock_get_tool_config.return_value = {'enabled': True, 'allow_others_from_group_msgs': True}
    tools = get_permitted_tools(is_group=True)
    assert len(tools) > 0

    mock_get_tool_config.return_value = {'enabled': True, 'allow_others_from_group_msgs': False}
    tools = get_permitted_tools(is_group=True)
    assert len(tools) == 0

@patch('tools.get_tool_config')
def test_get_permitted_tools_direct(mock_get_tool_config):
    from tools import get_permitted_tools
    mock_get_tool_config.return_value = {'enabled': True, 'allow_others_from_direct_msgs': True}
    tools = get_permitted_tools(is_direct=True)
    assert len(tools) > 0

    mock_get_tool_config.return_value = {'enabled': True, 'allow_others_from_direct_msgs': False}
    tools = get_permitted_tools(is_direct=True)
    assert len(tools) == 0

def test_get_permitted_tools_missing_self_developed(tmp_path):
    from tools import get_permitted_tools, AVAILABLE_TOOLS
    
    def mock_sd_tool(): pass
    mock_sd_tool.__module__ = 'tools.self_developed.mock'
    
    if mock_sd_tool not in AVAILABLE_TOOLS:
        AVAILABLE_TOOLS.append(mock_sd_tool)
        
    mock_mod = MagicMock()
    mock_mod.__file__ = "/path/to/missing/file.py"
    sys.modules['tools.self_developed.mock'] = mock_mod
    
    with patch('os.path.exists', return_value=False):
        tools = get_permitted_tools()
        assert mock_sd_tool not in tools
        assert mock_sd_tool not in AVAILABLE_TOOLS
        
    del sys.modules['tools.self_developed.mock']

def test_tools_init_os_loading():
    # Force reload of tools module under different OS platforms
    with patch('platform.system', return_value='Windows'):
        if 'tools' in sys.modules:
            del sys.modules['tools']
        import tools
        
    with patch('platform.system', return_value='Linux'):
        if 'tools' in sys.modules:
            del sys.modules['tools']
        import tools
        
    # Reload for default OS
    if 'tools' in sys.modules:
        del sys.modules['tools']
    import tools

def test_tools_init_self_developed_no_list():
    with patch('platform.system', return_value='Windows'):
        with patch('importlib.import_module') as mock_import:
            # Module loaded but missing AVAILABLE_SELF_DEVELOPED_TOOLS
            mock_import.return_value = MagicMock(spec=[])
            if 'tools' in sys.modules:
                del sys.modules['tools']
            import tools

def test_load_tools_from_directory_exception(tmp_path):
    from tools import _load_tools_from_directory
    pkg_dir = tmp_path / "err_tools"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "err_tool.py").write_text("import missing_module")
    
    # Should not raise exception
    _load_tools_from_directory(str(pkg_dir), "err_tools")
