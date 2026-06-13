import pytest
import subprocess
from unittest.mock import patch, MagicMock
from tools.macos.bash import run_bash_command

def test_macos_bash_success(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="Hello Mac\n", stderr="")
    
    result = run_bash_command("echo 'Hello Mac'")
    assert "STDOUT:\nHello Mac\n" in result

def test_macos_bash_stderr(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="Error\n")
    
    result = run_bash_command("ls /fake")
    assert "STDERR:\nError\n" in result

def test_macos_bash_no_output(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = MagicMock(stdout="", stderr="")
    
    result = run_bash_command("touch fake.txt")
    assert "executed successfully with no output" in result

def test_macos_bash_timeout(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=120))
    
    result = run_bash_command("sleep 1000")
    assert "timed out after 120 seconds" in result
