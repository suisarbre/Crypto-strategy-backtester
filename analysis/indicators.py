# indicators.py
# [LEGACY] This module is kept for backward compatibility with JsonStrategyLogic.
# New Python strategies should implement their own indicator calculation or use a shared library.
import numpy as np
"""
[DEPRECATED] 
This module is kept for backward compatibility with legacy `JsonStrategyLogic` and `strategies.json` visualization.
New strategies should use `cpp_extension` (via `IndicatorFactory`) or implement their own `calculate_indicators` method.
"""
import pandas as pd
import ta
import config as cfg

def get_rational_quadratic_kernel(src, lookback, relative_weight, lookback_mult=5):
    y_hat = src.copy()
    src_np = src.values
    length = len(src)
    calc_start = 0
    
    for i in range(calc_start, length):
        current_weight = 0.0
        cumulative_weight = 0.0
        # Standardized lookback range
        for j in range(max(0, i - lookback * lookback_mult), i + 1):
            w = (1 + (np.power(i - j, 2) / (2 * np.power(relative_weight, 2)))) ** (-relative_weight)
            current_weight += src_np[j] * w
            cumulative_weight += w
        if cumulative_weight != 0:
            y_hat.iloc[i] = current_weight / cumulative_weight
    return y_hat

def add_indicators(df, conf):
    df = df.copy()
    df['src'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    df['rsi'] = ta.momentum.rsi(df['src'], window=int(conf['rsi_length'])).fillna(50)
    
    esa = ta.trend.ema_indicator(df['src'], window=int(conf['wt_channel_len']))
    d = ta.trend.ema_indicator((df['src'] - esa).abs(), window=int(conf['wt_channel_len']))
    ci = (df['src'] - esa) / (0.015 * d)
    df['wt1'] = ta.trend.ema_indicator(ci, window=int(conf['wt_avg_len'])).fillna(0)

    df['cci'] = ta.trend.cci(df['high'], df['low'], df['src'], window=int(conf['cci_length'])).fillna(0)
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=int(conf['adx_length'])).fillna(0)
    
    atr_period = getattr(cfg, 'ATR_PERIOD', 14)
    df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=atr_period).fillna(0)
    df['ema_200'] = ta.trend.ema_indicator(df['src'], window=getattr(cfg, 'EMA_FILTER_PERIOD', 200)).fillna(0)
    # [FIX] Add EMA for strategy filter (dynamic period from conf)
    df['ema'] = ta.trend.ema_indicator(df['close'], window=int(conf.get('ema_period', 200))).fillna(df['close'])

    if conf.get('use_kernel', False):
        mult = getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)
        df['kernel'] = get_rational_quadratic_kernel(df['src'], conf['kernel_lookback'], conf['kernel_weight'], lookback_mult=mult)
        df['kernel_rising'] = df['kernel'] > df['kernel'].shift(1)
        df['kernel_falling'] = df['kernel'] < df['kernel'].shift(1)
    else:
        # [FIX] Kernel disabled - use simple momentum
        df['kernel'] = df['close']
        df['kernel_rising'] = df['close'] > df['close'].shift(1)
        df['kernel_falling'] = df['close'] < df['close'].shift(1)

    # [NEW] Choppiness Index (100 * Log10(Sum(TR, n) / (MaxHigh - MinLow)) / Log10(n))
    chop_len = 14
    # Calculate True Range (TR)
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    
    df['high_len'] = df['high'].rolling(window=chop_len).max()
    df['low_len'] = df['low'].rolling(window=chop_len).min()
    df['tr_sum'] = df['tr'].rolling(window=chop_len).sum()
    
    range_len = df['high_len'] - df['low_len']
    range_len = range_len.replace(0, 0.0001) 
    
    df['chop'] = 100 * np.log10(df['tr_sum'] / range_len) / np.log10(chop_len)
    df['chop'] = df['chop'].fillna(50)

    # [NEW] SuperTrend (Basic implementation for Trend Filter)
    # ATR period 10, Multiplier 3 (Standard)
    # Can optmize later
    st_period = 10
    st_mult = getattr(cfg, 'SUPERTREND_FACTOR', 3.0) # Configurable Multiplier
    st_atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=st_period).fillna(0)
    
    # Calculate Basic Upper/Lower Bands
    basic_upper = (df['high'] + df['low']) / 2 + st_mult * st_atr
    basic_lower = (df['high'] + df['low']) / 2 - st_mult * st_atr
    
    # Initialize Final Bands
    df['st_upper'] = basic_upper
    df['st_lower'] = basic_lower
    df['supertrend'] = df['close'] # Just init
    
    # Logic loop (A bit slow in Python, but needed for SuperTrend recursive logic)
    # Using simple recursive calculation (vectorization is hard for stateful ST)
    
    # Pre-calculate arrays for speed
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    upper = basic_upper.values
    lower = basic_lower.values
    supertrend = np.zeros(len(df))
    final_upper = np.zeros(len(df))
    final_lower = np.zeros(len(df))
    
    # Initialize first values
    supertrend[0] = close[0]
    final_upper[0] = upper[0]
    final_lower[0] = lower[0]
    
    for i in range(1, len(df)):
        # Final Upper Band
        if basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i-1]
            
        # Final Lower Band
        if basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
            final_lower[i] = basic_lower[i]
        else:
             final_lower[i] = final_lower[i-1]
             
        # SuperTrend
        if supertrend[i-1] == final_upper[i-1]:
            if close[i] > final_upper[i]:
                supertrend[i] = final_lower[i]
            else:
                supertrend[i] = final_upper[i]
        else:
            if close[i] < final_lower[i]:
                supertrend[i] = final_upper[i]
            else:
                supertrend[i] = final_lower[i]
                
    df['supertrend'] = supertrend
    # 1 = UpTrend (Green), -1 = DownTrend (Red)
        
    df.dropna(inplace=True)
    return df

def add_dynamic_indicators(df, strategy_json, config=None):
    """
    Parses 'definitions.indicators' from strategy_json and adds them to the DataFrame.
    """
    if not strategy_json: return df
    if config is None: config = {}
    
    try:
        import json
        if isinstance(strategy_json, str):
            strat = json.loads(strategy_json)
        else:
            strat = strategy_json
            
        indicators = strat.get('definitions', {}).get('indicators', [])
        
        for ind in indicators:
            name = ind.get('name')
            type_ = ind.get('type')
            source_col = ind.get('source', 'close')
            
            # Resolve Length (Handle int or string reference to config)
            raw_length = ind.get('length', 14)
            length = 14
            
            if isinstance(raw_length, int):
                length = raw_length
            elif isinstance(raw_length, str):
                if raw_length.isdigit():
                    length = int(raw_length)
                else:
                    # Look up in config (e.g., 'rsi_length' -> 14)
                    length = int(config.get(raw_length, 14))
            
            # Map source (Handle 'high_low_close' for ATR)
            if source_col not in df.columns and source_col != 'high_low_close':
                continue
                
            if type_ == 'ema':
                df[name] = ta.trend.ema_indicator(df[source_col], window=length).fillna(0)
            elif type_ == 'sma':
                df[name] = ta.trend.sma_indicator(df[source_col], window=length).fillna(0)
            elif type_ == 'rsi':
                df[name] = ta.momentum.rsi(df[source_col], window=length).fillna(50)
            elif type_ == 'atr':
                df[name] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=length).fillna(0)
                
    except Exception as e:
        print(f"Error adding dynamic indicators: {e}")
        
    return df