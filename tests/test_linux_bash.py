import pytest
import subprocess
from unittest.mock import patch, MagicMock
from tools.linux.bash import run_bash_command

def test_run_bash_command_success(mocker):
    """Test bash command successful execution with stdout."""
    # Mock permissions
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="Hello Bash\n", stderr="")
    
    result = run_bash_command("echo 'Hello Bash'")
    assert "STDOUT:\nHello Bash\n" in result
    mock_run.assert_called_once_with(
        "echo 'Hello Bash'",
        shell=True,
        capture_output=True,
        text=True,
        timeout=120
    )

def test_run_bash_command_stderr(mocker):
    """Test bash command with stderr output."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="Error executing\n")
    
    result = run_bash_command("ls /fake")
    assert "STDERR:\nError executing\n" in result

def test_run_bash_command_no_output(mocker):
    """Test bash command with no output."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="")
    
    result = run_bash_command("touch fake.txt")
    assert "executed successfully with no output" in result

def test_run_bash_command_timeout(mocker):
    """Test bash command timeout."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_run = mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="sleep 1000", timeout=120))
    
    result = run_bash_command("sleep 1000")
    assert "timed out after 120 seconds" in result

def test_run_bash_command_exception(mocker):
    """Test bash command general exception."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_run = mocker.patch('subprocess.run', side_effect=Exception("Unexpected failure"))
    
    result = run_bash_command("crash")
    assert "Error executing command: Unexpected failure" in result
