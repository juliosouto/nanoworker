import pytest
from unittest.mock import patch, MagicMock
from database import get_db, init_db, get_config, set_config, get_encryption_key, is_sensitive_key, encrypt_value, decrypt_value, set_ide_config, get_ide_config

def test_encryption_key(tmp_path):
    import database
    orig_path = database.KEY_PATH
    database.KEY_PATH = str(tmp_path / 'enc.key')
    
    key1 = get_encryption_key()
    assert key1 is not None
    key2 = get_encryption_key()
    assert key1 == key2
    
    database.KEY_PATH = orig_path

def test_is_sensitive_key():
    assert is_sensitive_key('MY_API_KEY') is True
    assert is_sensitive_key('TOKEN_ABC') is True
    assert is_sensitive_key('USER_PASSWORD') is True
    assert is_sensitive_key('APP_SECRET') is True
    assert is_sensitive_key('NORMAL_CONFIG') is False

def test_encrypt_decrypt():
    val = "my_secret_data"
    enc = encrypt_value(val)
    assert enc != val
    assert enc.startswith('gAAAA')
    
    dec = decrypt_value(enc)
    assert dec == val

def test_decrypt_invalid():
    assert decrypt_value("not_encrypted") == "not_encrypted"

def test_db_config(mock_db_path):
    init_db()
    
    # Test setting config
    set_config("TEST_KEY", "TEST_VAL")
    
    # Test getting config
    val = get_config("TEST_KEY")
    assert val == "TEST_VAL"
    
    # Test default
    assert get_config("MISSING_KEY", "DEFAULT") == "DEFAULT"

def test_ide_config(mock_db_path):
    init_db()
    
    set_ide_config("IDE_KEY", "IDE_VAL")
    assert get_ide_config("IDE_KEY") == "IDE_VAL"
    assert get_ide_config("MISSING", "DEF") == "DEF"


