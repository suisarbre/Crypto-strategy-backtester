
import sys
import os
import numpy as np
import cpp_engine
import json

def test_parity_json():
    print("=== Testing Optimizer Parity: Legacy (Hardcoded) vs Generic (JSON) ===")
    
    # 1. Synthesize Data (More Trend)
    n = 3000
    # Create a sine wave trend + noise
    t = np.linspace(0, 4*np.pi, n)
    trend = 100 * np.sin(t) + np.linspace(1000, 1200, n)
    close = trend + np.random.normal(0, 5, n)
    high = close + np.abs(np.random.normal(0, 2, n))
    low = close - np.abs(np.random.normal(0, 2, n))
    open_p = close + np.random.normal(0, 1, n)
    
    # Ensure all positive
    close = np.abs(close)
    high = np.abs(high)
    low = np.abs(low)
    open_p = np.abs(open_p)
    
    # 2. Define Params
    # Legacy Format: Dict of Lists
    ranges = {
        "rsi": [14.0],
        "wt_ch": [10.0],
        "wt_avg": [21.0],
        "cci": [20.0],
        "adx_len": [14.0],
        "k": [8.0],
        
        # Filters (Disabled to force trades)
        "adx_th": [0.0],
        "chop_threshold": [100.0],
        "lev": [1.0],
        "sl_multiplier": [3.0],
        "ema_period": [140.0],
        "use_ema_filter": [0.0],
        "use_adx_filter": [0.0]
    }
    
    # Generic Format: Lists
    # Indicators
    ind_names = ["rsi_length", "wt_channel_len", "wt_avg_len", "cci_length", "adx_length", "neighbors"]
    ind_vals = [[14.0], [10.0], [21.0], [20.0], [14.0], [8.0]] 
    
    # Filters
    # Map legacy keys to generic keys
    filt_names = ["adx_threshold", "chop_threshold", "leverage", "sl_multiplier", "ema_period", "use_ema_filter", "use_adx_filter"]
    filt_vals = [[0.0], [100.0], [1.0], [3.0], [140.0], [0.0], [0.0]]
    
    # Load JSON Strategy
    strat_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'strategies.json')
    with open(strat_path, "r") as f:
        strategy_json = f.read()
    
    # Constants
    min_trades = 1 # Relaxed
    max_trades = 1000
    max_mdd = 0.5
    start_bal = 100.0
    fee = 0.001
    tp = 0.99
    sl = 0.03
    k_look = 9
    k_weight = 8.0
    k_mult = 5
    
    # 3. Running Legacy
    print("\n[Legacy] Running optimize_grid_search...")
    import time
    t0 = time.time()
    res_legacy = cpp_engine.optimize_grid_search(
        open_p, high, low, close,
        ranges,
        k_look, k_weight, k_mult,
        sl, tp, fee,
        min_trades, max_trades, max_mdd,
        140, # ema_period fixed arg used in legacy
        14, # atr_period fixed arg
        start_bal
    )
    t_legacy = time.time() - t0
    print(f"   Done in {t_legacy:.4f}s. Results: {len(res_legacy)}")
    
    # 4. Running Generic (JSON)
    print("\n[Generic-JSON] Running optimize_generic...")
    t0 = time.time()
    res_generic = cpp_engine.optimize_generic(
        open_p, high, low, close,
        ind_names, ind_vals,
        filt_names, filt_vals,
        strategy_json, # [NEW argument]
        min_trades, max_trades, max_mdd, start_balance=start_bal,
        fee=fee, tp_ratio=tp, sl_ratio=sl,
        kernel_lookback=k_look, kernel_weight=k_weight, kernel_lookback_mult=k_mult
    )
    t_generic = time.time() - t0
    print(f"   Done in {t_generic:.4f}s. Results: {len(res_generic)}")
    
    # 5. Compare
    if not res_legacy and not res_generic:
        print("[Skipped] No trades found for both.")
        return

    # Check best match
    best_l = res_legacy[0]
    best_g = res_generic[0]
    
    print(f"\n[Comparison]")
    print(f"Legacy Best Score: {best_l['best_score']:.6f} (Bal: {best_l['balance']:.2f})")
    print(f"Generic Best Score: {best_g['best_score']:.6f} (Bal: {best_g['balance']:.2f})")
    
    diff = abs(best_l['best_score'] - best_g['best_score'])
    if diff < 1e-6:
        print("\n[SUCCESS] Scores Match!")
    else:
        print(f"\n[FAILURE] Score Mismatch! Diff: {diff}")
        print("Legacy Params:", best_l['best_params'])
        print("Generic Params:", best_g['best_params'])
        exit(1)

if __name__ == "__main__":
    test_parity_json()
