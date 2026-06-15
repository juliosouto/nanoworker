import pytest
import os
import json
import hashlib
from unittest.mock import patch, MagicMock

from tools.macos import document_saver as macos_ds
from tools.linux import document_saver as linux_ds
from tools.windows import document_saver as windows_ds

saver_modules = [macos_ds, linux_ds, windows_ds]

@pytest.fixture(params=saver_modules)
def ds_module(request):
    return request.param

def test_save_extracted_document_file_path(ds_module, mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.makedirs')
    mocker.patch('builtins.open', mocker.mock_open(read_data=b'\xff\xd8\xff test data'))
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    res = ds_module.save_extracted_document("category", {"key": "value"}, {"meta": "data"}, "/fake/path.jpg")
    
    assert "saved successfully" in res
    mock_cursor.execute.assert_called_once()
    assert "category" in mock_cursor.execute.call_args[0][1]

def test_save_extracted_document_db_image(ds_module, mocker):
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {'image_base64': 'path:/local/fake.png'}
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    mocker.patch('os.path.exists', side_effect=lambda p: True)
    mocker.patch('os.makedirs')
    mocker.patch('builtins.open', mocker.mock_open(read_data=b'\x89PNG\r\n\x1a\n test png'))
    
    res = ds_module.save_extracted_document("category", {"key": "value"}, None, None)
    
    assert "saved successfully" in res
    assert mock_cursor.execute.call_count == 2 # 1 for select, 1 for insert

def test_save_extracted_document_db_base64(ds_module, mocker):
    import base64
    b64_data = base64.b64encode(b'%PDF-1.4 test pdf').decode('utf-8')
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {'image_base64': f"data:image/pdf;base64,{b64_data}"}
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    mocker.patch('os.makedirs')
    mocker.patch('builtins.open', mocker.mock_open())
    
    res = ds_module.save_extracted_document("category", {}, None, None)
    assert "saved successfully" in res

def test_save_extracted_document_no_image(ds_module, mocker):
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    res = ds_module.save_extracted_document("category", {}, None, None)
    assert "Error: No recent image found" in res

def test_save_extracted_document_invalid_path(ds_module, mocker):
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {'image_base64': 'path:/local/fake.png'}
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    mocker.patch('os.path.exists', return_value=False)
    
    res = ds_module.save_extracted_document("category", {}, None, None)
    assert "not found" in res

def test_save_extracted_document_magic_bytes(ds_module, mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.makedirs')
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    magics = [
        b'GIF89a data',
        b'RIFFxxxxWEBP data',
        b'ftypheic data',
        b'ftypiso data' # mp4
    ]
    
    for magic in magics:
        mocker.patch('builtins.open', mocker.mock_open(read_data=magic))
        res = ds_module.save_extracted_document("cat", {}, {}, "/fake.img")
        assert "saved successfully" in res

def test_save_extracted_document_db_error(ds_module, mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.makedirs')
    mocker.patch('builtins.open', mocker.mock_open(read_data=b'data'))
    
    mock_db = MagicMock()
    mock_db.cursor.side_effect = Exception("DB Connection Failed")
    mocker.patch.object(ds_module, 'get_db', return_value=mock_db)
    
    res = ds_module.save_extracted_document("cat", {}, {}, "/fake.img")
    assert "Error saving to database" in res
