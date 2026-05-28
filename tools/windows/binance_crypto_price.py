import requests

def get_binance_crypto_price(symbol: str = "BTCUSDT") -> str:
    """Fetches the current price of a cryptocurrency using the Binance API.
    
    Args:
        symbol (str): The trading pair symbol to fetch the price for (e.g., 'BTCUSDT', 'ETHUSDT').
            Defaults to 'BTCUSDT'.
            
    Returns:
        str: A formatted string containing the current price of the cryptocurrency, or an error message.
    """
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'price' in data:
            return f"The current price of {data['symbol']} on Binance is {data['price']}."
        else:
            return "Error: Symbol not found in the Binance API response."
            
    except requests.exceptions.RequestException as e:
        return f"Error fetching price from Binance: {str(e)}"
