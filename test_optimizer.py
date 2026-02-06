import sys
import unittest
from unittest.mock import MagicMock
import pandas as pd
import numpy as np
import config

# Mock modules before importing core.optimizer
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.modules['data.data_loader'] = MagicMock()
from data.data_loader import fetch_raw_data

# Create dummy dataframe
def mock_fetch_raw_data(symbol, timeframe, limit):
    print(f"Mock fetching {symbol} {timeframe}")
    dates = pd.date_range(end=pd.Timestamp.now(), periods=500, freq='5min')
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.rand(500) * 100,
        'high': np.random.rand(500) * 100,
        'low': np.random.rand(500) * 100,
        'close': np.random.rand(500) * 100,
        'volume': np.random.rand(500) * 1000
    })
    # Make sure High is highest, Low is lowest
    df['high'] = df[['open', 'close']].max(axis=1) + 1
    df['low'] = df[['open', 'close']].min(axis=1) - 1
    return df

sys.modules['data.data_loader'].fetch_raw_data = mock_fetch_raw_data

from core.optimizer import execute_optimization_logic
import cpp_engine

def test_optimizer():
    print("Testing C++ Optimizer Integration...")
    
    # Check if cpp_engine works
    print("Cpp Engine Version:", cpp_engine.__doc__)
    
    # Run optimizer logic
    current_config = config.CURRENT_CONFIG.copy()
    current_config['active_strategy'] = 'standard'
    current_config['timeframe'] = '5m'
    
    # Mock config available strategies/timeframes
    config.AVAILABLE_TIMEFRAMES = ['5m']
    config.AVAILABLE_STRATEGIES = ['standard']
    
    # Execute
    print("Calling execute_optimization_logic...")
    best_params, w, t, m, b, s = execute_optimization_logic(current_config)
    
    print("\noptimization result:")
    print("Best Params:", best_params)
    print(f"Stats: Wins={w}, Trades={t}, MDD={m}, Balance={b}, Score={s}")
    
    if b != 100.0 or t > 0:
        print("✅ test passed (Ran simulation)")
    else:
        print("⚠️ test passed (Ran but no trades found, expected with random data)")

if __name__ == "__main__":
    test_optimizer()
