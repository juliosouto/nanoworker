import pytest
import json
import urllib.error
from unittest.mock import patch, MagicMock

from tools.macos import maps as macos_maps
from tools.linux import maps as linux_maps
from tools.windows import maps as windows_maps

map_modules = [macos_maps, linux_maps, windows_maps]

@pytest.fixture(params=map_modules)
def maps_module(request):
    return request.param

def test_search_map_success(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps([{"lat": "1.0", "lon": "2.0", "display_name": "Test Place"}]).encode('utf-8')
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    # We use an enter context manager in maps.py: `with urllib.request.urlopen(req) as response:`
    mock_response.__enter__.return_value = mock_response
    
    res = maps_module.search_map("query")
    assert "Test Place" in res
    assert "1.0" in res

def test_search_map_empty(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps([]).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.search_map("query")
    assert "No map results found" in res

def test_search_map_url_error(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=urllib.error.URLError("Failed"))
    res = maps_module.search_map("query")
    assert "Error performing map search" in res

def test_search_map_exception(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=Exception("Failed"))
    res = maps_module.search_map("query")
    assert "Unexpected error" in res

def test_search_all_locations_success(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "elements": [
            {"lat": 1.0, "lon": 2.0, "tags": {"name": "McDonalds", "addr:street": "Main St", "addr:housenumber": "123"}}
        ]
    }).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.search_all_locations_on_maps("McDonald's", "New York")
    assert res["total_found"] == 1
    assert res["locations"][0]["name"] == "McDonalds"
    assert res["locations"][0]["street"] == "Main St"

def test_search_all_locations_remark(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"remark": "Runtime error"}).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.search_all_locations_on_maps("McDonald's", "New York")
    assert "error" in res
    assert "Runtime error" in res["error"]

def test_search_all_locations_url_error(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=urllib.error.URLError("Failed"))
    res = maps_module.search_all_locations_on_maps("McDonald's", "New York")
    assert "error" in res
    assert "Overpass API Error" in res["error"]

def test_search_all_locations_exception(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=Exception("Failed"))
    res = maps_module.search_all_locations_on_maps("McDonald's", "New York")
    assert "error" in res
    assert "Unexpected error" in res["error"]

def test_get_coordinates_success(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps([{"lat": "1.0", "lon": "2.0", "display_name": "Test Place"}]).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.get_coordinates("query")
    assert res["lat"] == 1.0
    assert res["lon"] == 2.0
    assert res["full_name"] == "Test Place"

def test_get_coordinates_empty(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps([]).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.get_coordinates("query")
    assert "error" in res
    assert "Location not found" in res["error"]

def test_get_coordinates_exception(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=Exception("Failed"))
    res = maps_module.get_coordinates("query")
    assert "error" in res
    assert "Error fetching coordinates" in res["error"]

def test_calculate_route_success(maps_module, mocker):
    mock_response = MagicMock()
    route_data = {
        "routes": [
            {
                "distance": 15000,
                "duration": 1800,
                "legs": [
                    {
                        "steps": [
                            {"maneuver": {"type": "turn", "modifier": "left"}, "name": "Main St"},
                            {"maneuver": {"type": "arrive"}}
                        ]
                    }
                ]
            }
        ]
    }
    mock_response.read.return_value = json.dumps(route_data).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.calculate_route(1.0, 1.0, 2.0, 2.0, include_steps=True)
    assert res["distance_km"] == 15.0
    assert res["time_minutes"] == 30.0
    assert "Turn left onto main st" in res["steps"]

def test_calculate_route_empty(maps_module, mocker):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({}).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mocker.patch('urllib.request.urlopen', return_value=mock_response)
    
    res = maps_module.calculate_route(1.0, 1.0, 2.0, 2.0)
    assert "error" in res
    assert "Route could not be calculated" in res["error"]

def test_calculate_route_exception(maps_module, mocker):
    mocker.patch('urllib.request.urlopen', side_effect=Exception("Failed"))
    res = maps_module.calculate_route(1.0, 1.0, 2.0, 2.0)
    assert "error" in res
    assert "Error calculating route" in res["error"]
