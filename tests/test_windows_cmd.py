import pytest
import subprocess
from unittest.mock import patch, MagicMock
from tools.windows.cmd import run_windows_command

def test_windows_cmd_success(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="Hello Win\n", stderr="")
    
    result = run_windows_command("echo Hello Win")
    assert "STDOUT:\nHello Win\n" in result

def test_windows_cmd_stderr(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="Error\n")
    
    result = run_windows_command("dir /fake")
    assert "STDERR:\nError\n" in result

def test_windows_cmd_no_output(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="")
    
    result = run_windows_command("cd .")
    assert "executed successfully with no output" in result

def test_windows_cmd_timeout(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="timeout", timeout=120))
    
    result = run_windows_command("timeout 1000")
    assert "timed out after 120 seconds" in result
