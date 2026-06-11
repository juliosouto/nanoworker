import json
import urllib.request
import urllib.parse
import urllib.error

def search_map(query: str, limit: int = 5) -> str:
    """
    Performs a map search using the public Nominatim OpenStreetMap API.
    
    Args:
        query: The address or location to search for.
        limit: The maximum number of results to return (default is 5).
        
    Returns:
        A JSON string containing a list of search results, where each result 
        typically includes latitude, longitude, and display name.
        Returns an error message if the search fails.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': query,
        'format': 'json',
        'limit': limit
    }
    
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    req = urllib.request.Request(
        full_url, 
        headers={'User-Agent': 'Nanoworker-MapTool/1.0'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
            results = json.loads(data)
            
            if not results:
                return f"No map results found for query: '{query}'"
                
            return json.dumps(results, indent=2, ensure_ascii=False)
            
    except urllib.error.URLError as e:
        return f"Error performing map search for '{query}': {str(e)}"
    except Exception as e:
        return f"Unexpected error performing map search for '{query}': {str(e)}"


def search_all_locations_on_maps(brand: str, city: str) -> dict:
    """
    Searches for all locations of a specific brand within a given city using the Overpass API.
    
    Args:
        brand: Name or brand of the establishment (e.g., 'McDonalds').
        city: Name of the city to bound the search (e.g., 'New York').
    """
    url = "https://overpass-api.de/api/interpreter"
    
    # Handle apostrophes in Regex (e.g., McDonald's -> McDonald.?s)
    brand_regex = brand.replace("'", ".?")
    
    # admin_level=8 guarantees the search area is the exact municipality
    query = f"""
    [out:json][timeout:90];
    area["name"="{city}"]["admin_level"="8"]->.searchArea;
    (
      node["name"~"{brand_regex}",i](area.searchArea);
      way["name"~"{brand_regex}",i](area.searchArea);
      relation["name"~"{brand_regex}",i](area.searchArea);
    );
    out center;
    """
    
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(
        url, 
        data=data,
        headers={
            'User-Agent': 'Nanoworker-MapTool/1.0',
            'Accept': '*/*'
        }
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result_data = response.read()
            json_response = json.loads(result_data)
            
            if "remark" in json_response:
                return {"error": f"Overpass API Remark: {json_response['remark']}"}
            
            elements = json_response.get("elements", [])
            results = []
            
            for elem in elements:
                lat = elem.get("lat") or elem.get("center", {}).get("lat")
                lon = elem.get("lon") or elem.get("center", {}).get("lon")
                tags = elem.get("tags", {})
                
                results.append({
                    "name": tags.get("name", brand),
                    "street": tags.get("addr:street", "Not provided"),
                    "number": tags.get("addr:housenumber", "N/A"),
                    "lat": lat,
                    "lon": lon
                })
                
            return {"total_found": len(results), "locations": results}
            
    except urllib.error.URLError as e:
        return {"error": f"Overpass API Error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


def get_coordinates(location: str) -> dict:
    """
    Fetches the geographic coordinates (latitude and longitude) of a location using Nominatim.
    
    Args:
        location: Name of the city, address, or place to search.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location, "format": "json", "limit": 1}
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    req = urllib.request.Request(
        full_url, 
        headers={'User-Agent': 'Nanoworker-MapTool/1.0'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            if data:
                return {
                    "lat": float(data[0]["lat"]), 
                    "lon": float(data[0]["lon"]), 
                    "full_name": data[0]["display_name"]
                }
            return {"error": "Location not found."}
    except Exception as e:
        return {"error": f"Error fetching coordinates: {str(e)}"}


def calculate_route(lon_origin: float, lat_origin: float, lon_dest: float, lat_dest: float, include_steps: bool = False) -> dict:
    """
    Calculates the driving distance and travel time between two points using OSRM.
    
    Args:
        lon_origin: Longitude of the starting point.
        lat_origin: Latitude of the starting point.
        lon_dest: Longitude of the destination.
        lat_dest: Latitude of the destination.
        include_steps: If true, returns a list of turn-by-turn navigation instructions.
    """
    coordinates = f"{lon_origin},{lat_origin};{lon_dest},{lat_dest}"
    steps_param = "true" if include_steps else "false"
    url = f"http://router.project-osrm.org/route/v1/driving/{coordinates}?overview=false&steps={steps_param}"
    
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Nanoworker-MapTool/1.0'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            if data.get("routes"):
                route = data["routes"][0]
                result = {
                    "distance_km": round(route["distance"] / 1000, 2), 
                    "time_minutes": round(route["duration"] / 60, 2)
                }
                
                if include_steps and "legs" in route and len(route["legs"]) > 0:
                    steps = route["legs"][0].get("steps", [])
                    instructions = []
                    for step in steps:
                        maneuver = step.get("maneuver", {})
                        instruction = maneuver.get("type", "")
                        modifier = maneuver.get("modifier", "")
                        name = step.get("name", "")
                        
                        desc = instruction
                        if modifier:
                            desc += f" {modifier}"
                        if name:
                            desc += f" onto {name}"
                            
                        desc = desc.capitalize()
                        if desc and desc != "Arrive":
                            instructions.append(desc)
                            
                    result["steps"] = instructions
                    
                return result
            return {"error": "Route could not be calculated."}
    except Exception as e:
        return {"error": f"Error calculating route: {str(e)}"}
