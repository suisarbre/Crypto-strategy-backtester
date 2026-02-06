import pandas as pd
import numpy as np
import json
import config as cfg

# Dummy Data
data = {
    'timestamp': pd.date_range(start='2024-01-01', periods=10, freq='5min'),
    'open': [100, 101, 102, 103, 104, 103, 102, 101, 100, 99],
    'high': [101, 102, 103, 104, 105, 104, 103, 102, 101, 100],
    'low':  [99, 100, 101, 102, 103, 102, 101, 100, 99, 98],
    'close': [101, 102, 103, 104, 103, 102, 101, 100, 99, 98],
    'final_signal': [1, 0, 0, 0, -1, 0, 0, 0, 0, 0] # 1=Long, -1=Rev Short
}
df = pd.DataFrame(data)

print("Starting Simulation...")
try:
    # Copied Logic from dashboard.py
    markers = []
    position = 0 # 0, 1, -1
    partial_done = False
    entry_price = 0.0
    
    # SL Config
    sl_ratio = getattr(cfg, 'SL_RATIO', 0.03)
    leverage = getattr(cfg, 'DEFAULT_LEVERAGE', 3)
    
    stats = {'long': 0, 'short': 0, 'exit': 0, 'sl': 0, 'partial': 0}
    
    for idx, row in df.iterrows():
        ts = int(row['timestamp'].timestamp())
        sig = row['final_signal']
        close = row['close']
        low = row['low']
        high = row['high']
        
        # A. Check Stop Loss (Independent of Signal)
        if position != 0:
            # Calculate PnL for Low/High (Worst case)
            if position == 1:
                # Long SL: Check Low
                pnl = (low - entry_price) / entry_price
                lev_pnl = pnl * leverage
                if lev_pnl <= -sl_ratio:
                    position = 0
                    stats['sl'] += 1
                    markers.append({'time': ts, 'position': 'belowBar', 'color': '#c10015', 'shape': 'circle', 'text': 'SL'})
                    continue # Trade Closed
                    
            elif position == -1:
                # Short SL: Check High
                pnl = (entry_price - high) / entry_price
                lev_pnl = pnl * leverage
                if lev_pnl <= -sl_ratio:
                    position = 0
                    stats['sl'] += 1
                    markers.append({'time': ts, 'position': 'aboveBar', 'color': '#c10015', 'shape': 'circle', 'text': 'SL'})
                    continue # Trade Closed

        # B. Signal Processing
        if position == 0:
            if sig == 1:
                position = 1
                partial_done = False
                entry_price = close
                stats['long'] += 1
                markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'LONG'})
            elif sig == -1:
                position = -1
                partial_done = False
                entry_price = close
                stats['short'] += 1
                markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'SHORT'})
                
        elif position == 1: # Holdings Long
            if sig == -1: # Reverse Short
                position = -1
                partial_done = False
                entry_price = close
                stats['short'] += 1
                markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'Rev SHORT'})
            elif sig == 0: # Partial Exit (Standard Strategy Logic)
                if not partial_done:
                    partial_done = True
                    stats['partial'] += 1
                    markers.append({'time': ts, 'position': 'aboveBar', 'color': '#f2c037', 'shape': 'square', 'text': 'Partial'})
                    
        elif position == -1: # Holding Short
            if sig == 1: # Reverse Long
                position = 1
                partial_done = False
                entry_price = close
                stats['long'] += 1
                markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'Rev LONG'})
            elif sig == 0: # Partial Exit
                if not partial_done:
                    partial_done = True
                    stats['partial'] += 1
                    markers.append({'time': ts, 'position': 'belowBar', 'color': '#f2c037', 'shape': 'square', 'text': 'Partial'})

    print("Success!")
    print(markers)

except Exception as e:
    print(f"CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()
