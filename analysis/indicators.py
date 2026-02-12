# indicators.py
import numpy as np
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

    if conf.get('use_kernel', False):
        mult = getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)
        df['kernel'] = get_rational_quadratic_kernel(df['src'], conf['kernel_lookback'], conf['kernel_weight'], lookback_mult=mult)
        df['kernel_rising'] = df['kernel'] > df['kernel'].shift(1)
        df['kernel_falling'] = df['kernel'] < df['kernel'].shift(1)
    else:
        df['kernel_rising'] = True
        df['kernel_falling'] = True

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
    # For speed, we might want to move this to C++ later or use a library that supports it efficiently.
    # For now, let's use a simplified vectorized approximation or stick to standard library if available.
    # 'pandas_ta' has supertrend, but 'ta' library might not.
    # Let's skip heavy loop and use simple close > ema filter enhancement instead for now to stay fast?
    # NO, user asked for "SuperTrend". We will implement a fast numba/numpy version if possible, or just standard loop.
    # Since this is run on 5000 candles or optimization, loop is okay.
    
    bu = basic_upper.values
    bl = basic_lower.values
    close = df['close'].values
    
    # Final arrays
    fu = np.zeros(len(df))
    fl = np.zeros(len(df))
    trend = np.zeros(len(df)) # 1: Up, -1: Down
    
    # Init first values
    fu[0] = bu[0]
    fl[0] = bl[0]
    trend[0] = 1
    
    for i in range(1, len(df)):
        # Calculate Final Upper
        if (bu[i] < fu[i-1]) or (close[i-1] > fu[i-1]):
            fu[i] = bu[i]
        else:
            fu[i] = fu[i-1]
            
        # Calculate Final Lower
        if (bl[i] > fl[i-1]) or (close[i-1] < fl[i-1]):
            fl[i] = bl[i]
        else:
            fl[i] = fl[i-1]
            
        # Determine Trend
        prev_trend = trend[i-1]
        if prev_trend == 1:
            if close[i] < fl[i]:
                trend[i] = -1
            else:
                trend[i] = 1
        else: # prev == -1
            if close[i] > fu[i]:
                trend[i] = 1
            else:
                trend[i] = -1

    df['supertrend_trend'] = trend
    # 1 = UpTrend (Green), -1 = DownTrend (Red)
        
    df.dropna(inplace=True)
    return df