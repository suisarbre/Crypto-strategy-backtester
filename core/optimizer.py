import itertools
from datetime import datetime
import sys
import config as cfg
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
from core.backtester import run_deep_backtest

def execute_optimization_logic(current_config, custom_ranges=None):
    """
    Optimizes strategy parameters based on current configuration.
    Tests available strategies to find the best settings.
    If custom_ranges is provided, it uses those ranges instead of generating default ones.
    """
    start_time = datetime.now()
    print(f"\n[{start_time.strftime('%H:%M')}] [Optimization] Starting Precise Strategy & Parameter Optimization...")
    
    # 1.   ()
    df_raw_origin = fetch_raw_data(cfg.SYMBOL, cfg.TIMEFRAME, cfg.MAX_FETCH_LIMIT)
    if df_raw_origin is None: 
        return None, 0, 0, 0, 0
    
    # [NEW] Get Timeframes
    timeframes_to_test = cfg.AVAILABLE_TIMEFRAMES if hasattr(cfg, 'AVAILABLE_TIMEFRAMES') else ['5m']
    strategies_to_test = cfg.AVAILABLE_STRATEGIES if hasattr(cfg, 'AVAILABLE_STRATEGIES') else ['standard']
    
    print(f"   >>> Timeframes to Test: {timeframes_to_test}")
    print(f"   >>> Strategies to Test: {strategies_to_test}")

    # [WFA Logic]
    wfa_window = getattr(cfg, 'WFA_WINDOW_SIZE', 15000)
    train_ratio = getattr(cfg, 'WFA_TRAIN_RATIO', 0.7)

    # 1. Window Slicing ( N )
    if len(df_raw_origin) > wfa_window:
        df_raw_origin = df_raw_origin.tail(wfa_window).copy().reset_index(drop=True)
    
    # 2. IS / OOS Split
    total_bars = len(df_raw_origin)
    oos_size = int(total_bars * (1.0 - train_ratio)) # : 30%
    min_is_size = 2000
    
    df_is = df_raw_origin
    df_oos = None
    
    if total_bars >= (min_is_size + oos_size):
        split_idx = total_bars - oos_size
        df_is = df_raw_origin.iloc[:split_idx].copy()
        df_oos = df_raw_origin.iloc[split_idx:].copy()
        print(f"\n [WFA Split] Window={total_bars} (Train Ratio={train_ratio})")
        print(f"   => In-Sample (Train): {len(df_is)} bars (0 ~ {split_idx})")
        print(f"   => Out-of-Sample (Test): {len(df_oos)} bars ({split_idx} ~ end)")
    else:
        print(f"\n[Warning] Not enough data for OOS test (Total={total_bars})")
    
    #     
    #   fetch_raw_data    Warning .
    #    config.TIMEFRAME  'tf'  .
    # , fetch_raw_data     OOS  .
    #      fetch_raw_data   
    #   df_raw_origin  ,
    #   Multi-Timeframe   5m  15m    .
    # ,       ...
    # OOS     .
    
    #    :
    # df_raw_origin     (config.TIMEFRAME ).
    #    for tf in timeframes_to_test: 
    # tf config.TIMEFRAME     .
    #   for tf in ...    ''  
    #   ...
    pass # (This block replaces the initial setup to hint subsequent changes)

    #    
    global_best_score = -999
    global_best_params = current_config.copy()
    global_best_wins = 0
    global_best_trades = 0
    global_best_mdd = 0
    global_best_balance = getattr(cfg, 'START_BALANCE', 100.0)
    
    # === [Multi-Timeframe Loop] ===
    for tf in timeframes_to_test:
        print(f"\n Testing Timeframe: {tf}")
        
        # === [Multi-Strategy Loop] ===
        for strategy_name in strategies_to_test:
            print(f"    Testing Strategy: {strategy_name.upper()} ({tf})")
            
            #   
            local_config = current_config.copy()
            local_config['active_strategy'] = strategy_name 
            local_config['timeframe'] = tf # [NEW]  
            # local_config['max_bars_back'] = 3000 # [Removed] User config (25000) should prevail
            
            # 2.  ( )
            best_score = -999
            best_params = local_config.copy()
            best_wins = 0
            best_trades = 0
            best_mdd = 0
            best_balance = getattr(cfg, 'START_BALANCE', 100.0)
            
            # Coarse Scanning    
            #  [2000, 3000] ,    ( 25000) 
            target_bars = local_config.get('max_bars_back', 3000)
            bars_list = [target_bars] 
            
            #     (Float )
            def get_range(val, step=2):
                val = int(val)
                low = max(1, val - step)
                return sorted(list(set([low, val, val + step])))

            def get_fine_range(val, step=1, count=1, min_val=1, max_val=None, is_float=False):
                if not is_float:
                    val = int(val)
                    offsets = range(-count, count + 1) 
                    res = []
                    for o in offsets:
                        new_val = val + (o * step)
                        if new_val < min_val: continue
                        if max_val is not None and new_val > max_val: continue
                        res.append(new_val)
                    return sorted(list(set(res)))
                else:
                    val = float(val)
                    offsets = range(-count, count + 1)
                    res = []
                    for o in offsets:
                        new_val = val + (o * step)
                        if new_val < min_val: continue
                        if max_val is not None and new_val > max_val: continue
                        res.append(round(new_val, 2))
                    return sorted(list(set(res)))

            # 3.   
            rsi_range = get_range(local_config['rsi_length'])
            wt_ch_range = get_range(local_config['wt_channel_len'])
            wt_avg_range = get_range(local_config['wt_avg_len'])
            cci_range = get_range(local_config['cci_length'], 3)
            adx_len_range = get_range(local_config['adx_length'])
            
            adx_th_range = [20, 25, 30]
            # [Fix] Increase min neighbors to 9+ to reduce noise
            k_range = [9, 11, 13, 15]
            
            # [Safety] Use configured leverage range
            leverage_range = getattr(cfg, 'LEVERAGE_TEST_RANGE', [1, 2, 3])
            
            # [ATR Trailing Stop Range]
            sl_mult_range = [0.0]
            if getattr(cfg, 'USE_ATR_SL', False):
                sl_mult_range = getattr(cfg, 'ATR_TRAIL_SCAN_RANGE', [3.0, 4.0, 5.0])
            
            total_iter = (len(bars_list) * len(rsi_range) * len(wt_ch_range) * len(wt_avg_range) * len(cci_range) * len(adx_len_range))
            count = 0
            
            # [Fix]   (fetch logic handles caching internally, but we need fresh specific tf)
            # data_loader.fetch_raw_data uses 'fetch_OHLCV' which takes timeframe.
            # So we must call fetch for EACH timeframe loop.
            try:
                df_raw_tf = fetch_raw_data(cfg.SYMBOL, tf, cfg.MAX_FETCH_LIMIT)
                if df_raw_tf is None or len(df_raw_tf) < 500:
                    print(f"      Running out of data for {tf}, skipping...")
                    continue
                
                # [WFA OOS Split inside Loop]
                #      
                df_optim = df_raw_tf
                if len(df_raw_tf) > wfa_window:
                    df_optim = df_raw_tf.tail(wfa_window).copy().reset_index(drop=True)

                current_total = len(df_optim)
                current_oos_size = int(current_total * (1.0 - train_ratio))
                
                if current_total >= (min_is_size + current_oos_size):
                     split_idx = current_total - current_oos_size
                     #  IS  
                     df_optim = df_optim.iloc[:split_idx].copy().reset_index(drop=True)
            except Exception as e:
                print(f"      Error fetching data for {tf}: {e}")
                continue

            # [C++ Integration]
            try:
                import cpp_engine
                use_cpp = True
            except ImportError:
                use_cpp = False

            # 4. [Coarse Scanning]
            for bars in bars_list:
                df_slice_raw = df_optim.tail(bars).copy().reset_index(drop=True)
                
                if use_cpp:
                    # Construct ranges for C++
                    # keys must match optimizer.cpp expectations
                    if custom_ranges:
                        ranges = custom_ranges
                    else:
                        ranges = {
                            "rsi": list(rsi_range),
                            "wt_ch": list(wt_ch_range),
                            "wt_avg": list(wt_avg_range),
                            "cci": list(cci_range),
                            "adx_len": list(adx_len_range),
                            "adx_th": list(adx_th_range),
                            "chop_threshold": [40.0, 45.0, 50.0, 55.0, 60.0],
                            "k": list(k_range),
                            "lev": list(leverage_range),
                            "sl_multiplier": list(sl_mult_range),
                            "ema_period": [80.0, 100.0, 120.0, 140.0, 160.0, 180.0, 200.0],
                            "use_ema_filter": [0.0, 1.0],
                            "use_adx_filter": [0.0, 1.0]
                        }
                    
                    print(f"       C++ Coarse Scan ({bars} bars)...", end='\r')
                    
                    # Call C++ (Returns List of Dicts)
                    res_list = cpp_engine.optimize_grid_search(
                        df_slice_raw['open'].values.astype(float),
                        df_slice_raw['high'].values.astype(float),
                        df_slice_raw['low'].values.astype(float),
                        df_slice_raw['close'].values.astype(float),
                        ranges,
                        int(local_config.get('kernel_lookback', 9)),
                        float(local_config.get('kernel_weight', 8.0)),
                        int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
                        float(local_config.get('sl_ratio', 0.03)),
                        float(local_config.get('tp_ratio', 0.99)),
                        float(getattr(cfg, 'FEE_RATE', 0.001)),
                        int(cfg.OPTIMIZER_MIN_TRADES),
                        int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                        float(cfg.OPTIMIZER_MAX_MDD),
                        int(cfg.EMA_FILTER_PERIOD),
                        int(getattr(cfg, 'ATR_PERIOD', 14)),
                        float(getattr(cfg, 'START_BALANCE', 100.0))
                    )
                    
                    # [Coarse] Pick the single best from the top list
                    # Since C++ sorts them, we can just iterate.
                    for res in res_list:
                        if res['best_score'] > best_score:
                            best_score = res['best_score']
                            best_balance = res['balance']
                            best_wins = res['wins']
                            best_trades = res['trades']
                            best_mdd = res['mdd']
                            
                            best_params = local_config.copy()
                            best_params.update(res['best_params'])
                            best_params['max_bars_back'] = bars
                        
                    sys.stdout.write(f"\r       C++ Coarse Scan Done! Best: {best_balance:.2f}          \n")

                else:
                    # Python Fallback skipped
                    pass

            # 5. [Fine-Tuning]
            if best_score == -999:
                print(f"      [Warning] No valid results for {tf}/{strategy_name}.")
                continue
                
            print(f"       Fine-Tuning... (Best: {best_balance:.2f})")
            
            ft_rsi = get_fine_range(best_params['rsi_length'], count=1)
            ft_wt_ch = get_fine_range(best_params['wt_channel_len'], count=1)
            ft_wt_avg = get_fine_range(best_params['wt_avg_len'], count=1)
            ft_cci = get_fine_range(best_params['cci_length'], count=1)
            ft_adx_len = get_fine_range(best_params['adx_length'], count=1)
            ft_adx_th = get_fine_range(best_params['adx_threshold'], count=1)
            ft_adx_th = get_fine_range(best_params['adx_threshold'], count=1)
            ft_k = get_fine_range(best_params['neighbors'], count=1)
            
            # [Safety] Use configured leverage range for fine tuning as well (or keep strictly to refined)
            # Actually, for fine tuning, we should probably stick to the same range or nearby.
            # But to be safe, let's just re-use the user's allowed list.
            # If the user allows [1, 2, 3], and best was 3, we test [3]. If best was 2, we test [1, 2, 3].
            # Simply using the config list again is safest and easiest.
            ft_lev = getattr(cfg, 'LEVERAGE_TEST_RANGE', [1, 2, 3])
            
            # [ATR SL Fine Tuning]
            ft_sl_mult = [0.0]
            if best_params.get('sl_multiplier', 0.0) > 0.0:
                ft_sl_mult = get_fine_range(best_params['sl_multiplier'], step=0.5, count=1, min_val=1.0, is_float=True)

            # [C++ Integration]
            if use_cpp:
                # Construct ranges
                ranges = {
                    "rsi": list(ft_rsi),
                    "wt_ch": list(ft_wt_ch),
                    "wt_avg": list(ft_wt_avg),
                    "cci": list(ft_cci),
                    "adx_len": list(ft_adx_len),
                    "adx_th": list(ft_adx_th),
                    "k": list(ft_k),
                    "lev": list(ft_lev),
                    "sl_multiplier": list(ft_sl_mult), # [NEW]
                    "chop_threshold": [best_params.get("chop_threshold", 50.0)] # Fixed for FT or range?
                }
                
                ft_bars = best_params['max_bars_back']
                df_slice_ft = df_optim.tail(ft_bars).copy().reset_index(drop=True)
                
                res_list = cpp_engine.optimize_grid_search(
                        df_slice_ft['open'].values.astype(float),
                        df_slice_ft['high'].values.astype(float),
                        df_slice_ft['low'].values.astype(float),
                        df_slice_ft['close'].values.astype(float),
                        ranges,
                        int(best_params.get('kernel_lookback', 9)),
                        float(best_params.get('kernel_weight', 8.0)),
                        int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
                        float(best_params.get('sl_ratio', 0.03)),
                        float(best_params.get('tp_ratio', 0.99)),
                        float(getattr(cfg, 'FEE_RATE', 0.001)),
                        int(cfg.OPTIMIZER_MIN_TRADES),
                        int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                        float(cfg.OPTIMIZER_MAX_MDD),
                        int(cfg.EMA_FILTER_PERIOD),
                        int(getattr(cfg, 'ATR_PERIOD', 14)),
                        float(getattr(cfg, 'START_BALANCE', 100.0))
                    )
                
                # [Plateau Scoring: Robustness Check]
                # Goal: Select parameters where the NEIGHBORS also perform well.
                # Formula: Final_Score = Raw_Score * 0.7 + Avg_Neighbor_Score * 0.3
                
                plateau_best_score = -999
                plateau_best_res = None
                
                for res in res_list:
                    current_k = int(res['best_params']['neighbors'])
                    current_adx = int(res['best_params']['adx_threshold'])
                    
                    # Find neighbors in the Top-K list
                    # Definition of Neighbor: K +/- 2 AND ADX +/- 5
                    neighbors = []
                    for other in res_list:
                        if other is res: continue
                        
                        other_k = int(other['best_params']['neighbors'])
                        other_adx = int(other['best_params']['adx_threshold'])
                        
                        k_diff = abs(other_k - current_k)
                        adx_diff = abs(other_adx - current_adx)
                        
                        if k_diff <= 2 and adx_diff <= 5:
                            neighbors.append(other['best_score'])
                    
                    # Calculate Scores
                    raw_score = res['best_score']
                    neighbor_score = sum(neighbors) / len(neighbors) if neighbors else raw_score * 0.8 # Penalty if lonely
                    
                    # Weighted Final Score (Robustness Metric)
                    final_robust_score = (raw_score * 0.7) + (neighbor_score * 0.3)
                    
                    if final_robust_score > plateau_best_score:
                        plateau_best_score = final_robust_score
                        plateau_best_res = res
                
                # Apply the robust winner
                if plateau_best_res:
                     # Note: We update using the raw score of the robust selection, 
                     # but we chose it based on robust score.
                     if plateau_best_res['best_score'] > best_score: # Compare against previous GLOBAL/TF best
                        best_score = plateau_best_res['best_score']
                        best_params.update(plateau_best_res['best_params'])
                        best_balance = plateau_best_res['balance']
                        best_wins = plateau_best_res['wins']
                        best_trades = plateau_best_res['trades']
                        best_mdd = plateau_best_res['mdd']
                        best_mdd = plateau_best_res['mdd']
            else:
                 pass # Fallback skipped per migration request
            
            print(f"      [Done] Result: {best_balance:.2f} (Lev: {best_params.get('leverage')}x)")
            
            #  
            if best_score > global_best_score:
                global_best_score = best_score
                global_best_params = best_params.copy()
                global_best_wins = best_wins
                global_best_trades = best_trades
                global_best_mdd = best_mdd
                global_best_balance = best_balance

    # === [Final Report] ===
    print(f"\n[Result] Final Optimization Result (Multi-TF & Multi-Strategy) [Result]")
    sel_strat = global_best_params.get('active_strategy', 'UNKNOWN')
    sel_tf = global_best_params.get('timeframe', 'UNKNOWN')
    wr = (global_best_wins / global_best_trades * 100) if global_best_trades > 0 else 0
    print(f"   => Selected Strategy: {sel_strat.upper()} @ {sel_tf}")
    print(f"   => Performance: Bal {global_best_balance:.2f} | WR {wr:.1f}% ({global_best_wins}/{global_best_trades}) | MDD {global_best_mdd*100:.1f}%")
    print(f"   => Leverage: {global_best_params.get('leverage')}x")

    # [OOS Validation Report]
    if global_best_score != -999:
        try:
            print(f"\n[OOS] [Out-of-Sample] Verifying OOS Results... (Testing Future 5000 bars)")
            # Fetch full 15000 for winning timeframe
            best_tf = global_best_params.get('timeframe', '5m')
            df_full_final = fetch_raw_data(cfg.SYMBOL, best_tf, cfg.MAX_FETCH_LIMIT)
            
            if df_full_final is not None and len(df_full_final) >= 7000:
                oos_size_final = 5000
                warmup_buffer = 500 
                
                # OOS 
                split_idx_final = len(df_full_final) - oos_size_final
                
                # Buffer   (Warmup)
                calc_start_idx = max(0, split_idx_final - warmup_buffer)
                
                # Buffer   ->   -> (Buffer) 
                calc_start_idx = max(0, split_idx_final - warmup_buffer)
                
                # [WFA]   
                df_oos_extended = df_full_final.iloc[calc_start_idx:].copy()
                
                # Check timeframe consistency (ensure we have enough OOS bars)
                # We use extended buffer, so check if we have enough data
                if len(df_oos_extended) > (oos_size_final + 100):
                    # [Fix] Must calculate indicators/signals first!
                    # run_deep_backtest expects 'final_signal' column.
                    from analysis.indicators import add_indicators
                    from analysis.signals import generate_signals 
                    
                    # 1. Add Indicators (with params)
                    df_oos_extended = add_indicators(df_oos_extended, global_best_params)
                    
                    # 2. Generate Signals using OPTIMIZED params
                    df_oos_extended = generate_signals(df_oos_extended, global_best_params)
                    
                    # 3. Trim Buffer (Get pure OOS)
                    # Note: We want the last 5000 bars representing the future.
                    df_oos_final = df_oos_extended.tail(oos_size_final).copy()
                    
                    # Run deep backtest using PYTHON backtester (signals.py + cpp_engine inside)
                    # We utilize the Python wrapper to get nice stats
                    from core.backtester import run_deep_backtest
                    
                    # Note: run_deep_backtest expects 'config' dict.
                    oos_dict = run_deep_backtest(df_oos_final, global_best_params)
                    # run_deep_backtest returns tuple (bal, wins, trades, mdd, bal) or dict?
                    # Checking backtester.py again... 
                    # It returns values: bal, wins, trades, mdd, bal
                    # It does NOT return a dict. My previous code assumed a dict.
                    
                    oos_bal, oos_wins, oos_trades, oos_mdd, _ = oos_dict                    
                    
                    # Calculate Win Rate safely
                    oos_wr = (oos_wins / oos_trades * 100) if oos_trades > 0 else 0
                    
                    print(f"   [Done] OOS Performance: Bal {oos_bal:.2f} | WR {oos_wr:.1f}% ({oos_trades} trades) | MDD {oos_mdd*100:.2f}%")

                    
                    if oos_bal > getattr(cfg, 'START_BALANCE', 100.0):
                        print("   [Success] Congratulations! Profit on unseen data!.")
                    else:
                        print("   [Warning] Warning: Good in IS but, Loss in OOS. Potential Overfitting.")
                else:
                    print("   [Warning] Skipping OOS validation (Not enough data).")
            else:
                print("   [Warning] Not enough data for OOS validation.")
        except Exception as e:
            print(f"   [Warning] OOS Validation Error: {e}")


    return global_best_params, global_best_wins, global_best_trades, global_best_mdd, global_best_balance, global_best_score

def execute_smart_optimization(current_config):
    """
    Two-Phase Smart Optimization (Strategy A):
    Phase 1: Optimize Indicators & Model (RSI, WT, CCI, ADX_Len, K) with fixed Filters.
    Phase 2: Optimize Filters & Risk (ADX_Th, Chop, EMA, Lev, SL) with best Indicators.
    """
    print("\n   [Smart Optimization] Starting Phase 1: Indicators & Model...")
    
    # 1. Phase 1 Ranges
    # Optimize: RSI, WT, CCI, ADX_Len, Neighbors
    # Fix: ADX_Th, Chop, Lev, SL, EMA, Toggles
    
    # Helper to get base ranges
    # We use local helper from execute_optimization logic? No, need to duplicate or expose.
    # For simplicity, we define ranges here using same logic or just reduced ranges.
    
    # Let's extract range generation logic if possible, but for now hardcode "Standard" scan ranges
    # derived from config.
    
    def get_range(val, step=2):
        val = int(val)
        low = max(1, val - step)
        return sorted(list(set([low, val, val + step])))

    # Current Config
    cfg_rsi = int(current_config.get('rsi_length', 14))
    cfg_wt_ch = int(current_config.get('wt_channel_len', 10))
    cfg_wt_avg = int(current_config.get('wt_avg_len', 21))
    cfg_cci = int(current_config.get('cci_length', 20))
    cfg_adx_len = int(current_config.get('adx_length', 14))
    cfg_k = int(current_config.get('neighbors', 8))
    
    # Phase 1 Ranges
    ranges_p1 = {
        "rsi": get_range(cfg_rsi),
        "wt_ch": get_range(cfg_wt_ch),
        "wt_avg": get_range(cfg_wt_avg),
        "cci": get_range(cfg_cci, 3),
        "adx_len": get_range(cfg_adx_len),
        "k": [8, 12, 16], # Coarse scan for K
        # Fixed
        "adx_th": [25],
        "chop_threshold": [50.0],
        "lev": [current_config.get('leverage', 1)],
        "sl_multiplier": [current_config.get('sl_multiplier', 0.0)],
        "ema_period": [int(current_config.get('ema_period', 140))], # Default
        "use_ema_filter": [1.0],
        "use_adx_filter": [1.0]
    }
    
    # Run Phase 1
    res_p1 = execute_optimization_logic(current_config, custom_ranges=ranges_p1)
    
    if not res_p1:
        print("   [Smart Optimization] Phase 1 Failed. Returning None.")
        return None
        
    best_p1_params = res_p1[0] # extracting parameters
    print(f"   [Smart Optimization] Phase 1 Done. Best Score: {res_p1[5]:.2f}")
    
    # 2. Phase 2 Ranges
    # Fix: Indicators (to Best P1)
    # Optimize: Filters, Risk
    print("\n   [Smart Optimization] Starting Phase 2: Filters & Risk...")
    
    best_rsi = int(best_p1_params['rsi_length'])
    best_wt_ch = int(best_p1_params['wt_channel_len'])
    best_wt_avg = int(best_p1_params['wt_avg_len'])
    best_cci = int(best_p1_params['cci_length'])
    best_adx_len = int(best_p1_params['adx_length'])
    best_k = int(best_p1_params['neighbors'])
    
    ranges_p2 = {
        # Fixed to P1 Winners
        "rsi": [best_rsi],
        "wt_ch": [best_wt_ch],
        "wt_avg": [best_wt_avg],
        "cci": [best_cci],
        "adx_len": [best_adx_len],
        "k": [best_k],
        # Optimize Filters
        "adx_th": [20, 25, 30],
        "chop_threshold": [40.0, 50.0, 60.0],
        "ema_period": [80.0, 140.0, 200.0],
        "use_ema_filter": [0.0, 1.0],
        "use_adx_filter": [0.0, 1.0],
        # Optimize Risk
        "lev": getattr(cfg, 'LEVERAGE_TEST_RANGE', [1, 2, 3]),
        "sl_multiplier": getattr(cfg, 'ATR_TRAIL_SCAN_RANGE', [3.0, 4.0, 5.0]) if getattr(cfg, 'USE_ATR_SL', False) else [0.0]
    }
    
    # Run Phase 2
    res_p2 = execute_optimization_logic(current_config, custom_ranges=ranges_p2)
    
    print(f"   [Smart Optimization] Phase 2 Done. Best Score: {res_p2[5]:.2f}")
    return res_p2