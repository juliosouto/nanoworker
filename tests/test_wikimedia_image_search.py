import json
from unittest.mock import patch, Mock
from tools.linux.wikimedia_image_search import search_wikimedia_images

def test_search_wikimedia_images_success():
    """Test successful image search on Wikimedia Commons."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "query": {
            "pages": {
                "123": {
                    "title": "File:Test_Dog.jpg",
                    "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/test_dog.jpg"}]
                },
                "456": {
                    "title": "File:Test_Cat.jpg",
                    "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/test_cat.jpg"}]
                }
            }
        }
    }
    mock_response.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_response) as mock_get:
        result_str = search_wikimedia_images("pets", limit=2)
        
        # Verify the mock was called correctly
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["gsrsearch"] == "pets"
        assert kwargs["params"]["gsrlimit"] == 2
        
        # Verify the result
        result = json.loads(result_str)
        assert len(result) == 2
        assert result[0]["title"] == "Test_Dog.jpg"
        assert result[0]["url"] == "https://upload.wikimedia.org/wikipedia/commons/test_dog.jpg"
        assert result[1]["title"] == "Test_Cat.jpg"

def test_search_wikimedia_images_no_results():
    """Test search with no results."""
    mock_response = Mock()
    mock_response.json.return_value = {"batchcomplete": ""}
    mock_response.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_response):
        result = search_wikimedia_images("unknown_query_123")
        assert "Nenhuma imagem encontrada" in result

def test_search_wikimedia_images_error():
    """Test search with an API error."""
    with patch("requests.get", side_effect=Exception("API Timeout")):
        result = search_wikimedia_images("dog")
        assert "Erro ao pesquisar" in result
        assert "API Timeout" in result
