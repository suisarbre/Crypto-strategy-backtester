"""
Test C++ optimizer with EXACT same ranges as the failed optimizer run
"""
import numpy as np
from data.data_loader import fetch_raw_data
import cpp_engine

# Fetch data
df = fetch_raw_data("BTC/USDT", "15m", limit=15000)
train_size = int(15000 * 0.7)
df_train = df.iloc[:train_size].copy()

print(f"Testing on {len(df_train)} bars (same as optimizer)")

# EXACT ranges from optimizer output
ind_names = ['rsi_length', 'wt_channel_len', 'wt_avg_len', 'cci_length', 'adx_length', 'neighbors']
ind_values = [
    [12.0, 14.0, 16.0],  # rsi_length
    [8.0, 10.0, 12.0],   # wt_channel_len
    [19.0, 21.0, 23.0],  # wt_avg_len
    [17.0, 20.0, 23.0],  # cci_length
    [12.0, 14.0, 16.0],  # adx_length
    [8.0, 12.0, 16.0]    # neighbors
]

filt_names = ['adx_threshold', 'chop_threshold', 'leverage', 'sl_multiplier', 'ema_period', 'use_ema_filter', 'use_adx_filter']
filt_values = [
    [25.0],   # adx_threshold
    [45.0],   # chop_threshold
    [1.0],    # leverage
    [0.0],    # sl_multiplier
    [80.0],   # ema_period
    [1.0],    # use_ema_filter
    [1.0]     # use_adx_filter
]

print(f"\nTesting {3**6} = 729 combinations...")
print(f" Indicators: {len(ind_names)} params with 3 values each")
print(f" Filters: {len(filt_names)} params with 1 value each")

# Load strategies.json
import os
strat_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'strategies.json')
with open(strat_path) as f:
    strat_json = f.read()

print(f"\nCalling C++ optimize_generic...")
results = cpp_engine.optimize_generic(
    df_train['open'].values.astype(float),
    df_train['high'].values.astype(float),
    df_train['low'].values.astype(float),
    df_train['close'].values.astype(float),
    ind_names, ind_values,
    filt_names, filt_values,
    strat_json,
    10,      # min_trades (same as optimizer)
    2500,    # max_trades
    0.30,    # max_mdd (same as optimizer)
    100.0,   # start_balance
    0.001,   # fee
    0.99,    # tp_ratio
    0.03,    # sl_ratio
    9,       # kernel_lookback
    8.0,     # kernel_weight
    5        # kernel_lookback_mult
)

print(f"\nC++ returned {len(results)} results")

if len(results) > 0:
    print(f"\n[SUCCESS] Found {len(results)} valid strategies!")
    for i, r in enumerate(results[:5]):
        print(f"  [{i+1}] Trades={r.get('trades')}, Wins={r.get('wins')}, Bal={r.get('balance'):.2f}, MDD={r.get('mdd')*100:.1f}%")
        print(f"       Params: {r.get('best_params')}")
else:
    print(f"\n[PROBLEM] C++ returned 0 results - same as optimizer!")
    print(f"This means either:")
    print(f"  1. None of the 729 combinations meet MIN_TRADES=10 and MAX_MDD=0.30")
    print(f"  2. There's a bug in C++ optimize_generic parameter iteration")
    print(f"  3. The JSON strategy evaluator is failing all combinations")
