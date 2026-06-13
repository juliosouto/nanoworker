import pytest
from unittest.mock import patch, MagicMock

from tools.linux import scheduling as linux_sch
from tools.macos import scheduling as macos_sch
from tools.windows import scheduling as windows_sch
from utils.session import current_session_id

@pytest.fixture(params=[
    ("linux", linux_sch),
    ("macos", macos_sch),
    ("windows", windows_sch)
])
def sch_setup(request):
    return request.param

def test_schedule_task_cron(sch_setup, mocker):
    os_name, sch_module = sch_setup
    # Set the ContextVar value for the test
    token = current_session_id.set("sess-123")
    
    mock_conn = MagicMock()
    mocker.patch(f'tools.{os_name}.scheduling.get_db', return_value=mock_conn)
    
    res = sch_module.schedule_task("test", "do something", cron_expression="* * * * *")
    assert "Task scheduled successfully with recurrence" in res
    
    current_session_id.reset(token)

def test_schedule_task_oneshot(sch_setup, mocker):
    os_name, sch_module = sch_setup
    token = current_session_id.set("sess-123")
    
    mock_conn = MagicMock()
    mocker.patch(f'tools.{os_name}.scheduling.get_db', return_value=mock_conn)
    
    res = sch_module.schedule_task("test", "do something", process_after="2099-01-01 00:00:00")
    assert "Task scheduled successfully to run at" in res
    
    current_session_id.reset(token)

def test_schedule_task_no_session(sch_setup, mocker):
    os_name, sch_module = sch_setup
    token = current_session_id.set(None)
    
    mock_conn = MagicMock()
    mocker.patch(f'tools.{os_name}.scheduling.get_db', return_value=mock_conn)
    
    res = sch_module.schedule_task("test", "do something")
    assert "Error: No active session found" in res
    
    current_session_id.reset(token)

def test_list_scheduled_tasks(sch_setup, mocker):
    os_name, sch_module = sch_setup
    token = current_session_id.set("sess-123")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    mock_cursor.fetchall.return_value = [
        {
            "id": "job-1", "description": "test job", "cron_expression": None, 
            "next_run": "2099", "execution_count": 0, "max_executions": 1
        }
    ]
    mocker.patch(f'tools.{os_name}.scheduling.get_db', return_value=mock_conn)
    
    res = sch_module.list_scheduled_tasks()
    assert "Active Scheduled Tasks" in res
    assert "job-1" in res
    
    current_session_id.reset(token)

def test_delete_scheduled_task(sch_setup, mocker):
    os_name, sch_module = sch_setup
    token = current_session_id.set("sess-123")
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.rowcount = 1
    mocker.patch(f'tools.{os_name}.scheduling.get_db', return_value=mock_conn)
    
    res = sch_module.delete_scheduled_task("job-1")
    assert "successfully canceled" in res
    
    current_session_id.reset(token)
