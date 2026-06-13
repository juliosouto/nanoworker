import pytest
from unittest.mock import patch, MagicMock

from tools.linux import document_searcher as linux_ds
from tools.macos import document_searcher as macos_ds
from tools.windows import document_searcher as windows_ds

@pytest.fixture(params=[
    ("linux", linux_ds),
    ("macos", macos_ds),
    ("windows", windows_ds)
])
def ds_setup(request):
    return request.param

def test_search_documents_data_in_database_success(ds_setup, mocker):
    os_name, ds_module = ds_setup
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "file_hash": "hash123",
            "file_name": "receipt.pdf",
            "category": "receipt",
            "created_at": "2023-01-01",
            "extracted_data": '{"total": 50}',
            "metadata": '{"note": "lunch"}'
        }
    ]
    
    if os_name == "macos":
        mocker.patch('tools.macos.document_searcher.format_document_search_results', side_effect=lambda x: x)
        
    mocker.patch(f'tools.{os_name}.document_searcher.get_db', return_value=mock_conn)
    
    res = ds_module.search_documents_data_in_database(query="lunch")
    assert res["status"] == "success"
    assert res["count"] == 1
    assert res["data"][0]["file_name"] == "receipt.pdf"
    assert res["data"][0]["extracted_data"]["total"] == 50

def test_search_documents_data_in_database_empty(ds_setup, mocker):
    os_name, ds_module = ds_setup
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    mock_cursor.fetchall.return_value = []
    
    if os_name == "macos":
        mocker.patch('tools.macos.document_searcher.format_document_search_results', side_effect=lambda x: x)
        
    mocker.patch(f'tools.{os_name}.document_searcher.get_db', return_value=mock_conn)
    
    res = ds_module.search_documents_data_in_database()
    assert res["status"] == "success"
    assert "No documents found" in res["message"]

def test_search_documents_data_in_database_invalid_json(ds_setup, mocker):
    os_name, ds_module = ds_setup
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "file_hash": "hash123",
            "file_name": "receipt.pdf",
            "category": "receipt",
            "created_at": "2023-01-01",
            "extracted_data": '{invalid_json',
            "metadata": '{invalid_json'
        }
    ]
    
    if os_name == "macos":
        mocker.patch('tools.macos.document_searcher.format_document_search_results', side_effect=lambda x: x)
        
    mocker.patch(f'tools.{os_name}.document_searcher.get_db', return_value=mock_conn)
    
    res = ds_module.search_documents_data_in_database(query="*", limit=1)
    assert res["status"] == "success"
    assert res["data"][0]["extracted_data"] == {}
    assert res["data"][0]["metadata"] == {}

def test_search_documents_data_in_database_error(ds_setup, mocker):
    os_name, ds_module = ds_setup
    mocker.patch(f'tools.{os_name}.document_searcher.get_db', side_effect=Exception("DB Error"))
    
    res = ds_module.search_documents_data_in_database()
    assert res["status"] == "error"
    assert "DB Error" in res["message"]
