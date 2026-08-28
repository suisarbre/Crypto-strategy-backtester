import ccxt
import pandas as pd
import config as cfg
import utils

# [Network Fix] Force IPv4 (binanceus IPv6 error fix)
utils.apply_patches()

# Exchange instance (with server-time sync to avoid -1021 timestamp errors)
#
# Credentials are OPTIONAL and omitted entirely when blank: this module only
# calls public endpoints (fetch_ohlcv, fetch_ticker), which need no auth. Passing
# empty strings makes ccxt believe it is authenticated and turns a public-endpoint
# problem into a confusing auth error. See ADR-002 — there is no order code.
_auth = {}
if getattr(cfg, 'API_KEY', '') and getattr(cfg, 'SECRET_KEY', ''):
    _auth = {'apiKey': cfg.API_KEY, 'secret': cfg.SECRET_KEY}

exchange = ccxt.binanceus({
    **_auth,
    'enableRateLimit': True,
    'options': {
        'adjustForTimeDifference': True,   # auto-sync clock offset
        'recvWindow': 10000,               # 10s tolerance window
    },
})

# Pre-load server time offset before first request
try:
    exchange.load_time_difference()
except Exception:
    pass

def fetch_raw_data(symbol, timeframe, limit):
    try:
        # Pagination to fetch more than exchange limit (usually 1000)
        all_bars = []
        # Calculate approximately when to start: limit * minutes * 60 * 1000
        # This is a rough estimate, we'll fetch forward from a bit earlier to be safe
        
        # CCXT safely handles 'since'
        # For simple "get last N" with pagination:
        # 1. We just fetch in chunks loop? No, fetch_ohlcv with limit > 1000 might truncate.
        #    Some exchanges execute limit=5000 by themselves (e.g. some CCXT impls).
        #    Binance max is 1000.
        
        # Robust implementation: Fetch latest, then if needed fetch previous?
        # Or easier: fetch forward from (Now - N * interval).
        
        since = None
        if limit > 1000:
            # Parse timeframe to milliseconds
            duration_seconds = exchange.parse_timeframe(timeframe)
            duration_ms = duration_seconds * 1000
            now = exchange.milliseconds()
            since = now - (limit * duration_ms)
            
        all_bars = []
        current_since = since
        
        remaining = limit
        
        while remaining > 0:
            fetch_count = min(remaining, 1000) # Binance max 1000
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=fetch_count, since=current_since)
            
            if not bars:
                break
                
            all_bars.extend(bars)
            remaining -= len(bars)
            
            # Update since to the timestamp of the last bar + 1 timeframe (to avoid duplicates)
            last_time = bars[-1][0]
            # Next fetch starts from last candle + 1ms? Or better +1 timeframe?
            # CCXT usually inclusive 'since'. So next should be > last_time.
            # Using last_time + 1 is safest for general cases.
            current_since = last_time + 1
            
            if len(bars) < fetch_count: 
                # Exchange returned fewer than requested => End of data
                break
                
        # Truncate to exact limit if we got slightly more
        if len(all_bars) > limit:
            all_bars = all_bars[-limit:]

        df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"[Error] Data fetch failed: {e}")
        return None

def fetch_current_price(symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception:
        return None