import requests

def get_currency_or_metal_price(pair: str) -> str:
    """Fetches the current price of a fiat currency or metal using the AwesomeAPI.

    Args:
        pair (str): The currency or metal pair to fetch the price for (e.g., 'XAU-BRL', 'USD-BRL', 'EUR-BRL').

    Returns:
        str: A formatted string containing the current price, or an error message if the request fails.
    """
    url = f"https://economia.awesomeapi.com.br/json/last/{pair}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # The API returns a key like 'XAUBRL' for the input 'XAU-BRL'
        key = pair.replace('-', '').upper()
        
        if key in data:
            name = data[key].get('name', pair)
            bid = data[key].get('bid', '')
            return f"The current price of {name} is {bid}."
        else:
            return f"Error: Could not find data for the pair {pair}."
            
    except requests.exceptions.RequestException as e:
        return f"Error fetching price: {str(e)}"
    except (KeyError, ValueError) as e:
        return f"Error parsing the API response: {str(e)}"
