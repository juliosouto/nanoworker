import json
try:
    from tradingview_ta import TA_Handler, Interval
except ImportError:
    TA_Handler = None
    Interval = None

def get_stocks_indicators_and_analysis(symbol: str, screener: str = "america", exchange: str = "NASDAQ", interval: str = "1d") -> str:
    """Fetches the technical indicators and analysis for a given stock using TradingView data.
    
    Args:
        symbol (str): The stock symbol (e.g., 'TSLA', 'AAPL').
        screener (str): The screener to use (e.g., 'america', 'crypto', 'brazil'). Defaults to 'america'.
        exchange (str): The exchange the stock is traded on (e.g., 'NASDAQ', 'NYSE', 'BMFBOVESPA'). Defaults to 'NASDAQ'.
        interval (str): The interval for the analysis. Valid values are: '1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1W', '1M'. Defaults to '1d'.
            
    Returns:
        str: A JSON formatted string containing the recommendation summary and all indicators (like RSI).
    """
    if TA_Handler is None:
        return "Error: tradingview_ta is not installed. Please install it with 'pip install tradingview_ta'."
        
    interval_map = {
        '1m': Interval.INTERVAL_1_MINUTE,
        '5m': Interval.INTERVAL_5_MINUTES,
        '15m': Interval.INTERVAL_15_MINUTES,
        '30m': Interval.INTERVAL_30_MINUTES,
        '1h': Interval.INTERVAL_1_HOUR,
        '2h': Interval.INTERVAL_2_HOURS,
        '4h': Interval.INTERVAL_4_HOURS,
        '1d': Interval.INTERVAL_1_DAY,
        '1W': Interval.INTERVAL_1_WEEK,
        '1M': Interval.INTERVAL_1_MONTH,
    }
    
    interval_value = interval_map.get(interval, Interval.INTERVAL_1_DAY)
    
    try:
        ativo = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange,
            interval=interval_value
        )
        
        analise = ativo.get_analysis()
        
        result = {
            "summary": analise.summary,
            "indicators": analise.indicators
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return f"Error fetching analysis for {symbol}: {str(e)}"
