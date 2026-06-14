import pytest
from unittest.mock import patch, MagicMock

from tools.linux import memory as linux_mem
from tools.macos import memory as macos_mem
from utils.session import current_session_id

@pytest.fixture(params=[
    ("linux", linux_mem),
    ("macos", macos_mem)
])
def mem_setup(request):
    return request.param

def test_manage_persistent_memory_invalid_action(mem_setup):
    os_name, mem_module = mem_setup
    res = mem_module.manage_persistent_memory(action="invalid_action")
    assert "Invalid action" in res

def test_manage_persistent_memory_whatsapp_blocked(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "whatsapp:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    
    res = mem_module.manage_persistent_memory(action="list")
    assert "not available for WhatsApp" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_list_empty(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.get_all_user_memories', return_value=[])
    
    res = mem_module.manage_persistent_memory(action="list")
    assert "No persistent memories" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_list_success(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.get_all_user_memories', return_value=[{"id": 1, "instruction": "My memory"}])
    
    res = mem_module.manage_persistent_memory(action="list")
    assert "My memory" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_delete_missing_id(mem_setup, mocker):
    os_name, mem_module = mem_setup
    res = mem_module.manage_persistent_memory(action="delete")
    assert "memory_id is required" in res

def test_manage_persistent_memory_delete_success(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.delete_user_memory', return_value=True)
    
    res = mem_module.manage_persistent_memory(action="delete", memory_id=1)
    assert "has been deleted" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_delete_not_found(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.delete_user_memory', return_value=False)
    
    res = mem_module.manage_persistent_memory(action="delete", memory_id=1)
    assert "not found" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_add_missing_text(mem_setup, mocker):
    os_name, mem_module = mem_setup
    res = mem_module.manage_persistent_memory(action="add")
    assert "memory_text is required" in res

def test_manage_persistent_memory_add_success(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.add_user_memory', return_value=10)
    
    long_text = "A" * 200
    res = mem_module.manage_persistent_memory(action="add", memory_text=long_text)
    assert "Memory added with ID 10" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_update_missing_id(mem_setup, mocker):
    os_name, mem_module = mem_setup
    res = mem_module.manage_persistent_memory(action="update", memory_text="Test")
    assert "memory_id is required" in res

def test_manage_persistent_memory_update_success(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.update_user_memory', return_value=True)
    
    res = mem_module.manage_persistent_memory(action="update", memory_text="New Text", memory_id=1)
    assert "has been updated" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_check_channel_id_exception(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("DB Error")
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    
    # Just perform an action to trigger the exception block in channel checking
    res = mem_module.manage_persistent_memory(action="list")
    assert "DB Error" not in res  # It shouldn't crash
    current_session_id.reset(token)

def test_manage_persistent_memory_list_exception(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.get_all_user_memories', side_effect=Exception("List Error"))
    
    res = mem_module.manage_persistent_memory(action="list")
    assert "Error listing memories" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_delete_exception(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.delete_user_memory', side_effect=Exception("Delete Error"))
    
    res = mem_module.manage_persistent_memory(action="delete", memory_id=1)
    assert "Error deleting memory" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_add_exception(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.add_user_memory', side_effect=Exception("Add Error"))
    
    res = mem_module.manage_persistent_memory(action="add", memory_text="Text")
    assert "Error adding memory" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_update_not_found(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.update_user_memory', return_value=False)
    
    res = mem_module.manage_persistent_memory(action="update", memory_text="New Text", memory_id=1)
    assert "not found" in res
    current_session_id.reset(token)

def test_manage_persistent_memory_update_exception(mem_setup, mocker):
    os_name, mem_module = mem_setup
    token = current_session_id.set("sess-mock")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"channel_id": "web:123"}
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch(f'tools.{os_name}.memory.get_db', return_value=mock_conn)
    mocker.patch(f'tools.{os_name}.memory.update_user_memory', side_effect=Exception("Update Error"))
    
    res = mem_module.manage_persistent_memory(action="update", memory_text="New Text", memory_id=1)
    assert "Error updating memory" in res
    current_session_id.reset(token)
