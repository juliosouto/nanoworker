import pytest
import os
import shutil
from unittest.mock import patch, MagicMock

import database
from utils.setup_utils import (
    backup_database, setup_app_config, setup_ide_prompt,
    setup_ide_settings, setup_llm_config, setup_agents,
    setup_whatsapp_config, setup_workers_config, setup_tools_config
)

def test_backup_database(mocker):
    # Mock shutil.copy2 to avoid actually copying files
    mock_copy2 = mocker.patch('utils.setup_utils.shutil.copy2')
    
    backup_path = backup_database()
    
    assert backup_path.endswith('.db')
    assert 'bin/backups' in backup_path.replace('\\', '/')
    mock_copy2.assert_called_once()

def test_setup_app_config(mock_db_path):
    database.init_db()
    setup_app_config()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM app_config")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count > 0

def test_setup_ide_prompt(mock_db_path):
    database.init_db()
    setup_ide_prompt()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_config WHERE key = 'ide_prompt'")
    val = cursor.fetchone()
    conn.close()
    
    assert val is not None
    assert "Two-Step Execution Workflow" in val[0]

def test_setup_ide_settings(mock_db_path):
    database.init_db()
    setup_ide_settings()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ide_settings WHERE key = 'theme'")
    val = cursor.fetchone()
    conn.close()
    
    assert val is not None
    assert val[0] == 'dark'

def test_setup_llm_config(mock_db_path):
    database.init_db()
    setup_llm_config()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM llm_config")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count > 5  # Currently there are 16 models

def test_setup_agents(mock_db_path):
    database.init_db()
    setup_agents()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM agents WHERE id = 'agent-1'")
    val = cursor.fetchone()
    conn.close()
    
    assert val is not None
    assert val[0] == 'Default NanoWorker Agent'

def test_setup_whatsapp_config_insert(mock_db_path):
    database.init_db()
    
    # Delete row to trigger INSERT
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM whatsapp_config")
    conn.commit()
    conn.close()
    
    setup_whatsapp_config()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_enabled FROM whatsapp_config WHERE id = 1")
    val = cursor.fetchone()
    conn.close()
    
    assert val is not None
    assert val[0] == 1

def test_setup_whatsapp_config_update(mock_db_path):
    database.init_db()
    
    # Ensure there's a row to trigger UPDATE
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO whatsapp_config (id, bot_enabled) VALUES (1, 0)")
    conn.commit()
    conn.close()
    
    setup_whatsapp_config()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_enabled FROM whatsapp_config WHERE id = 1")
    val = cursor.fetchone()
    conn.close()
    
    assert val is not None
    assert val[0] == 1

def test_setup_workers_config(mock_db_path):
    database.init_db()
    setup_workers_config()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM workers_config")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count > 0

def test_setup_tools_config(mock_db_path):
    database.init_db()
    
    def dummy_tool(): pass
    dummy_tool.__name__ = 'test_tool'
    with patch('tools.AVAILABLE_TOOLS', [dummy_tool]):
        setup_tools_config()
        
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tools_config")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count > 0
