import pytest
from utils.security_utils import require_permission
from unittest.mock import patch

@require_permission('PERM_TEST')
def dummy_protected_function():
    return "success"

def test_require_permission_enabled(mocker):
    """Test that the wrapped function executes when the permission is enabled."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    result = dummy_protected_function()
    assert result == "success"

def test_require_permission_disabled(mocker):
    """Test that access is denied when the permission is disabled."""
    mocker.patch('utils.security_utils.get_config', return_value='false')
    result = dummy_protected_function()
    assert "Error: Access denied" in result
    assert "'PERM_TEST'" in result

def test_require_permission_default_disabled(mocker):
    """Test that access is denied by default if permission not set."""
    mocker.patch('utils.security_utils.get_config', return_value='false')
    result = dummy_protected_function()
    assert "Error: Access denied" in result
