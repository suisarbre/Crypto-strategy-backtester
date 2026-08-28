import itertools
from datetime import datetime
import sys
import config as cfg
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
from core.backtester import run_deep_backtest

import os
import json


def run_pso_optimization(df_slice, local_config, strategy_json_content, strategy_path=None):
    """
    Run PSO (Particle Swarm Optimization) on the given data slice.
    Per Architecture Report: Metaheuristic search for high-speed parameter discovery.
    Returns list of result dicts from C++ PSO engine.
    """
    try:
        import cpp_engine
    except ImportError:
        print("   [PSO] C++ engine not available, cannot run PSO.")
        return []
    
    # Build parameter bounds from STRATEGY_PARAMS config
    active_strat = local_config.get('active_strategy', 'standard')
    strat_space = getattr(cfg, 'STRATEGY_PARAMS', {}).get(active_strat, {})
    
    if not strat_space:
        print(f"   [PSO] No STRATEGY_PARAMS for strategy '{active_strat}'")
        return []
    
    param_names = []
    param_mins = []
    param_maxs = []
    
    for param, space in strat_space.items():
        if isinstance(space, dict) and space.get('type') == 'dynamic':
            # Dynamic params: use current value +/- step*width as bounds
            current_val = local_config.get(param, 14)
            step = space.get('step', 2)
            width = space.get('width', 3)
            param_names.append(param)
            param_mins.append(float(max(1, current_val - step * width)))
            param_maxs.append(float(current_val + step * width))
        elif isinstance(space, list) and len(space) > 0:
            param_names.append(param)
            param_mins.append(float(min(space)))
            param_maxs.append(float(max(space)))
    
    if not param_names:
        print("   [PSO] No parameters to optimize")
        return []
    
    # Build defaults from local_config (known-good values seed the swarm)
    param_defaults = [float(local_config.get(nm, (mn + mx) / 2))
                      for nm, mn, mx in zip(param_names, param_mins, param_maxs)]

    n_dims = len(param_names)
    base_swarm = int(getattr(cfg, 'PSO_SWARM_SIZE', 50))
    base_iters = int(getattr(cfg, 'PSO_MAX_ITERATIONS', 30))
    swarm_size = max(base_swarm, n_dims * 20)
    max_iters  = max(base_iters, n_dims * 6)

    print(f"   [PSO] Swarm={swarm_size}, Iterations={max_iters}, Dims={n_dims}")
    for name, lo, hi, dv in zip(param_names, param_mins, param_maxs, param_defaults):
        print(f"     {name}: [{lo}, {hi}] default={dv}")
    
    res_list = cpp_engine.optimize_pso(
        df_slice['open'].values.astype(float),
        df_slice['high'].values.astype(float),
        df_slice['low'].values.astype(float),
        df_slice['close'].values.astype(float),
        param_names, param_mins, param_maxs,
        param_defaults,
        strategy_json_content,
        int(cfg.OPTIMIZER_MIN_TRADES),
        int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
        float(cfg.OPTIMIZER_MAX_MDD),
        float(getattr(cfg, 'START_BALANCE', 100.0)),
        float(getattr(cfg, 'FEE_RATE', 0.001)),
        float(local_config.get('tp_ratio', 0.99)),
        float(local_config.get('sl_ratio', 0.03)),
        int(local_config.get('kernel_lookback', 9)),
        float(local_config.get('kernel_weight', 8.0)),
        int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
        swarm_size,
        max_iters,
    )
    
    return res_list


def display_trade_off_matrix(res_list):
    """
    Display the Trade-Off Matrix (per Financial Benchmarking Report):
    Top parameter sets ranked by different criteria.
    Set 1: Highest Absolute Return
    Set 2: Highest Sortino Ratio  
    Set 3: Highest Calmar Ratio
    Set 4: Lowest Beta (most market-neutral)
    """
    if not res_list or len(res_list) == 0:
        return
    
    print(f"\n{'='*70}")
    print(f" TRADE-OFF MATRIX (Financial Benchmarking)")
    print(f"{'='*70}")
    
    # Baseline info
    baseline = res_list[0].get('baseline_return', 0)
    print(f"  Buy-and-Hold Baseline Return: {baseline*100:.2f}%")
    
    # Sort by different criteria
    by_return = sorted(res_list, key=lambda x: x.get('total_return', 0), reverse=True)
    by_sortino = sorted(res_list, key=lambda x: x.get('sortino', 0), reverse=True)
    by_calmar = sorted(res_list, key=lambda x: x.get('calmar', 0), reverse=True)
    # Beta proxy: |total_return / baseline_return| → lower = more market-neutral
    by_beta = sorted(res_list, key=lambda x: abs(x.get('total_return', 0) / max(abs(baseline), 0.001)))
    
    def fmt_row(label, r):
        ret = r.get('total_return', 0) * 100
        srt = r.get('sortino', 0)
        cal = r.get('calmar', 0)
        pf = r.get('profit_factor', 0)
        alpha = r.get('alpha', 0) * 100
        mdd = r.get('mdd', 0) * 100
        bal = r.get('balance', 0)
        print(f"  {label:25s} | Ret {ret:+7.1f}% | Sortino {srt:6.2f} | Calmar {cal:6.2f} | PF {pf:5.2f} | Alpha {alpha:+6.1f}% | MDD {mdd:5.1f}% | Bal {bal:.1f}")
    
    print(f"\n  {'Category':<25s} | {'Return':>10s} | {'Sortino':>10s} | {'Calmar':>10s} | {'PF':>6s} | {'Alpha':>9s} | {'MDD':>7s} | {'Balance':>7s}")
    print(f"  {'-'*25}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*6}-+-{'-'*9}-+-{'-'*7}-+-{'-'*7}")
    
    fmt_row("Best Return", by_return[0])
    fmt_row("Best Sortino (Risk-Adj)", by_sortino[0])
    fmt_row("Best Calmar (Drawdown)", by_calmar[0])
    fmt_row("Most Market-Neutral", by_beta[0])
    
    # Primary recommendation (Sortino-ranked winner)
    print(f"\n  Primary Pick (Sortino): Bal={by_sortino[0].get('balance', 0):.1f}, Alpha={by_sortino[0].get('alpha', 0)*100:+.1f}%")
    print(f"{'='*70}\n")

def get_range(val, step=2):
    """
    Generates a range [val-step, val, val+step] ensuring min value >= 1.
    Used for 'dynamic' parameter types.
    """
    val = int(val)
    low = max(1, val - step)
    return sorted(list(set([low, val, val + step])))

def get_indicator_params_from_json():
    """
    Parses strategies.json to identify which parameters control indicators.
    Returns a set of parameter names (e.g., {'rsi_length', 'wt_channel_len'}).
    """
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'strategies.json')
    ind_params = set()
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Extract indicator parameters
            indicators = data.get('definitions', {}).get('indicators', [])
            for ind in indicators:
                for key, val in ind.items():
                    # Skip meta keys
                    if key in ['name', 'type', 'source']:
                        continue
                    # If value is a string and not a number, it's a parameter name
                    if isinstance(val, str) and not val.replace('.', '', 1).isdigit():
                        ind_params.add(val)
                        
        except Exception as e:
            print(f"[Warning] Failed to parse strategies.json: {e}")
            
    return ind_params

def transform_ranges_to_generic_format(ranges):
    """
    Convert old grid_search ranges dict to optimize_generic format.
    Returns: (ind_names, ind_values, filt_names, filt_values)
    """
    # Indicator keys - support BOTH short and long forms (different code paths use different formats)
    ind_short_keys = {'rsi', 'wt_ch', 'wt_avg', 'cci', 'adx_len', 'k'}
    ind_long_keys = {'rsi_length', 'wt_channel_len', 'wt_avg_len', 'cci_length', 'adx_length', 'neighbors'}
    
    # Map old short keys to new full names
    key_mapping = {
        'rsi': 'rsi_length',
        'wt_ch': 'wt_channel_len',
        'wt_avg': 'wt_avg_len',
        'cci': 'cci_length',
        'adx': 'adx_length',
        'adx_len': 'adx_length',  # Used in ranges
        'k': 'neighbors',
        'lev': 'leverage',
        'adx_threshold': 'adx_threshold',
        'adx_th': 'adx_threshold',  # Short key used in ranges
        'chop_threshold': 'chop_threshold',
        'ema_period': 'ema_period',
        'use_ema_filter': 'use_ema_filter',
        'use_adx_filter': 'use_adx_filter',
        'sl_multiplier': 'sl_multiplier'
    }
    
    ind_names = []
    ind_values = []
    filt_names = []
    filt_values = []
    
    for k, v in ranges.items():
        mapped_key = key_mapping.get(k, k)
        values_list = list(v) if isinstance(v, (list, tuple)) else [v]
        
        # Check if the ORIGINAL key is an indicator (short OR long form)
        if k in ind_short_keys or k in ind_long_keys:
            ind_names.append(mapped_key)
            ind_values.append([float(x) for x in values_list])
        else:
            filt_names.append(mapped_key)
            filt_values.append([float(x) for x in values_list])
    
    return ind_names, ind_values, filt_names, filt_values


def _failure_result():
    """Uniform failure shape for execute_optimization_logic — same 6-tuple as
    success, with params=None and score=-999, so callers never have to sniff
    tuple lengths or handle a bare None."""
    return None, 0, 0, 0, getattr(cfg, 'START_BALANCE', 100.0), -999


def execute_optimization_logic(current_config, custom_ranges=None, strategy_path=None, df=None):
    """
    Optimizes strategy parameters based on current configuration.
    Tests available strategies to find the best settings.
    If custom_ranges is provided, it uses those ranges instead of generating default ones.

    df: optional pre-sliced OHLCV window (used by execute_rolling_wfa). When
    given, it is used as-is for every timeframe instead of fetching, the caller
    owns any train/test splitting, and the final OOS validation is skipped —
    otherwise every "rolling" window would silently optimize on freshly fetched
    full data instead of its own slice.

    Returns: (best_params | None, wins, trades, mdd, balance, score) — always a
    6-tuple; score is -999 and best_params is None on failure.
    """
    start_time = datetime.now()
    print(f"\n[{start_time.strftime('%H:%M')}] [Optimization] Starting Precise Strategy & Parameter Optimization...")

    # Availability check only — the per-timeframe loop fetches its own data.
    if df is None:
        df_raw_origin = fetch_raw_data(cfg.SYMBOL, cfg.TIMEFRAME, cfg.MAX_FETCH_LIMIT)
        if df_raw_origin is None:
            return _failure_result()

    timeframes_to_test = cfg.AVAILABLE_TIMEFRAMES if hasattr(cfg, 'AVAILABLE_TIMEFRAMES') else ['5m']
    strategies_to_test = cfg.AVAILABLE_STRATEGIES if hasattr(cfg, 'AVAILABLE_STRATEGIES') else ['standard']

    print(f"   >>> Timeframes to Test: {timeframes_to_test}")
    print(f"   >>> Strategies to Test: {strategies_to_test}")

    # [WFA] In-sample split settings, applied per timeframe inside the loop.
    wfa_window = getattr(cfg, 'WFA_WINDOW_SIZE', 15000)
    train_ratio = getattr(cfg, 'WFA_TRAIN_RATIO', 0.7)
    min_is_size = 2000

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

            # 3. Research-backed ranges for KNN Lorentzian
            rsi_range = [9, 11, 14, 17, 21]
            wt_ch_range = [8, 9, 10, 11, 14]
            wt_avg_range = [9, 11, 13, 15]
            cci_range = [14, 17, 20, 23, 26]
            adx_len_range = [14, 17, 20, 23, 26]
            
            adx_th_range = [15, 20, 25, 30]
            k_range = [6, 8, 10, 12, 16]
            
            # [Safety] Use configured leverage range
            leverage_range = getattr(cfg, 'LEVERAGE_TEST_RANGE', [1, 2, 3])
            
            # [ATR Trailing Stop Range]
            sl_mult_range = [0.0]
            if getattr(cfg, 'USE_ATR_SL', False):
                sl_mult_range = getattr(cfg, 'ATR_TRAIL_SCAN_RANGE', [3.0, 4.0, 5.0])
            
            total_iter = (len(bars_list) * len(rsi_range) * len(wt_ch_range) * len(wt_avg_range) * len(cci_range) * len(adx_len_range))
            count = 0
            
            # Each timeframe needs its own fetch — unless the caller supplied a
            # pre-sliced window, which is used verbatim (the caller owns splits).
            try:
                if df is not None:
                    if len(df) < 500:
                        print(f"      Supplied window too small ({len(df)} bars), skipping...")
                        continue
                    df_optim = df.copy().reset_index(drop=True)
                else:
                    df_raw_tf = fetch_raw_data(cfg.SYMBOL, tf, cfg.MAX_FETCH_LIMIT)
                    if df_raw_tf is None or len(df_raw_tf) < 500:
                        print(f"      Running out of data for {tf}, skipping...")
                        continue

                    # [WFA] Trim to window, then drop the OOS tail from the
                    # in-sample data used for optimization.
                    df_optim = df_raw_tf
                    if len(df_raw_tf) > wfa_window:
                        df_optim = df_raw_tf.tail(wfa_window).copy().reset_index(drop=True)

                    current_total = len(df_optim)
                    current_oos_size = int(current_total * (1.0 - train_ratio))

                    if current_total >= (min_is_size + current_oos_size):
                        split_idx = current_total - current_oos_size
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
                            "chop_threshold": [38.0, 45.0, 53.0, 60.0],
                            "k": list(k_range),
                            "lev": list(leverage_range),
                            "sl_multiplier": list(sl_mult_range),
                            "ema_period": [50.0, 80.0, 120.0, 160.0, 200.0],
                            "use_ema_filter": [0.0, 1.0],
                            "use_adx_filter": [0.0, 1.0]
                        }
                    
                    print(f"       C++ Coarse Scan ({bars} bars)...", flush=True)

                    if not ranges:
                         print("[ERROR] 'ranges' dict is empty! Cannot run optimization.")
                         return _failure_result()

                    ind_names, ind_values, filt_names, filt_values = transform_ranges_to_generic_format(ranges)

                    if not ind_names:
                         print(f"[ERROR] ind_names is empty after transform! Raw ranges keys: {list(ranges.keys())}")
                         return _failure_result()

                    # Load strategies.json
                    strategy_json_content = ""
                    # Priority: 1. Argument, 2. Default Path
                    strat_path = strategy_path if strategy_path else os.path.join(os.path.dirname(__file__), '..', 'strategies', 'strategies.json')
                    if os.path.exists(strat_path):
                        with open(strat_path, 'r') as f:
                            strategy_json_content = f.read()
                    else:
                        print(f"\nWarning: strategies.json not found at {strat_path}")

                    # Call optimize_generic (JSON-based modular optimizer),
                    # or PSO if configured (per Architecture Report)
                    use_pso = getattr(cfg, 'USE_PSO', False)
                    
                    if use_pso:
                        print(f"   [PSO] Running Particle Swarm Optimization...", flush=True)
                        res_list = run_pso_optimization(df_slice_raw, local_config, strategy_json_content, strategy_path)
                        if not res_list and getattr(cfg, 'PSO_FALLBACK_TO_GRID', True):
                            print(f"   [PSO] Falling back to Grid Search...")
                            use_pso = False
                    
                    if not use_pso:
                        res_list = cpp_engine.optimize_generic(
                            df_slice_raw['open'].values.astype(float),
                            df_slice_raw['high'].values.astype(float),
                            df_slice_raw['low'].values.astype(float),
                            df_slice_raw['close'].values.astype(float),
                            ind_names, ind_values,
                            filt_names, filt_values,
                            strategy_json_content,
                            int(cfg.OPTIMIZER_MIN_TRADES),
                            int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                            float(cfg.OPTIMIZER_MAX_MDD),
                            float(getattr(cfg, 'START_BALANCE', 100.0)),
                            float(getattr(cfg, 'FEE_RATE', 0.001)),
                            float(local_config.get('tp_ratio', 0.99)),
                            float(local_config.get('sl_ratio', 0.03)),
                            int(local_config.get('kernel_lookback', 9)),
                            float(local_config.get('kernel_weight', 8.0)),
                            int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5))
                        )
                    
                    # [Benchmarking] Display Trade-Off Matrix (per Financial Benchmarking Report)
                    if res_list:
                        display_trade_off_matrix(res_list)
                    
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
                        
                    print(f"       Coarse Scan Done! Best: {best_balance:.2f}")

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
                    "chop_threshold": [best_params.get("chop_threshold", 50.0)], # Fixed for FT or range?
                    "ema_period": [best_params.get("ema_period", 140)], 
                    "use_ema_filter": [best_params.get("use_ema_filter", 1.0)],
                    "use_adx_filter": [best_params.get("use_adx_filter", 1.0)]
                }
                
                ft_bars = best_params['max_bars_back']
                df_slice_ft = df_optim.tail(ft_bars).copy().reset_index(drop=True)
                
                ind_names, ind_values, filt_names, filt_values = transform_ranges_to_generic_format(ranges)

                # Load strategy content to pass to the C++ engine.
                # Same priority as the coarse scan: explicit argument first —
                # this used to hardcode the default, so fine-tuning a repository
                # strategy silently scored against strategies.json instead.
                strat_path = strategy_path if strategy_path else os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), 'strategies', 'strategies.json')
                strategy_json_content = "{}"
                if os.path.exists(strat_path):
                    with open(strat_path, 'r') as f:
                        strategy_json_content = f.read()
                else:
                    print(f"Warning: strategies.json not found at {strat_path}")


                # 2. Call Generic Optimizer
                res_list = cpp_engine.optimize_generic(
                        df_slice_ft['open'].values.astype(float),
                        df_slice_ft['high'].values.astype(float),
                        df_slice_ft['low'].values.astype(float),
                        df_slice_ft['close'].values.astype(float),
                        ind_names, ind_values,
                        filt_names, filt_values,
                        strategy_json_content, # [NEW]
                        int(cfg.OPTIMIZER_MIN_TRADES),
                        int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                        float(cfg.OPTIMIZER_MAX_MDD),
                        float(getattr(cfg, 'START_BALANCE', 100.0)),
                        float(getattr(cfg, 'FEE_RATE', 0.001)),
                        float(best_params.get('tp_ratio', 0.99)),
                        float(best_params.get('sl_ratio', 0.03)),
                        int(best_params.get('kernel_lookback', 9)),
                        float(best_params.get('kernel_weight', 8.0)),
                        int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5))
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
    print(f"\n{'='*70}")
    print(f" FINAL OPTIMIZATION RESULT")
    print(f"{'='*70}")
    sel_strat = global_best_params.get('active_strategy', 'UNKNOWN')
    sel_tf = global_best_params.get('timeframe', 'UNKNOWN')
    wr = (global_best_wins / global_best_trades * 100) if global_best_trades > 0 else 0
    print(f"   Strategy: {sel_strat.upper()} @ {sel_tf}")
    print(f"   Performance: Bal {global_best_balance:.2f} | WR {wr:.1f}% ({global_best_wins}/{global_best_trades}) | MDD {global_best_mdd*100:.1f}%")
    print(f"   Leverage: {global_best_params.get('leverage')}x")
    
    # [Benchmarking] Display fitness function used
    optimizer_mode = "PSO (Particle Swarm)" if getattr(cfg, 'USE_PSO', False) else "Grid Search"
    print(f"   Optimizer: {optimizer_mode}")
    print(f"   Fitness: Sortino Ratio + MDD Penalty (per Architecture Report)")
    print(f"{'='*70}")

    # [OOS Validation Report] — skipped when the caller supplied the data
    # (e.g. rolling WFA), because the caller owns its own OOS split and this
    # fetch of the latest bars would overlap the supplied training window.
    if global_best_score != -999 and df is None:
        try:
            print(f"\n[OOS] [Out-of-Sample] Verifying OOS Results... (Testing Future 5000 bars)")
            # Fetch full 15000 for winning timeframe
            best_tf = global_best_params.get('timeframe', '5m')
            df_full_final = fetch_raw_data(cfg.SYMBOL, best_tf, cfg.MAX_FETCH_LIMIT)
            
            if df_full_final is not None and len(df_full_final) >= 7000:
                oos_size_final = 5000
                warmup_buffer = 500

                # OOS split, extended backwards by a warmup buffer so the
                # indicators are warm by the time the pure OOS region starts.
                split_idx_final = len(df_full_final) - oos_size_final
                calc_start_idx = max(0, split_idx_final - warmup_buffer)
                df_oos_extended = df_full_final.iloc[calc_start_idx:].copy()
                
                # Check timeframe consistency (ensure we have enough OOS bars)
                # We use extended buffer, so check if we have enough data
                if len(df_oos_extended) > (oos_size_final + 100):
                    # run_deep_backtest expects a 'final_signal' column, so
                    # compute indicators + signals with the OPTIMIZED params,
                    # then trim the warmup buffer to get the pure OOS region.
                    df_oos_extended = add_indicators(df_oos_extended, global_best_params)
                    df_oos_extended = generate_signals(df_oos_extended, global_best_params)
                    df_oos_final = df_oos_extended.tail(oos_size_final).copy()

                    oos_bal, oos_wins, oos_trades, oos_mdd, _ = run_deep_backtest(df_oos_final, global_best_params)

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


def execute_rolling_wfa(current_config, strategy_path=None):
    """
    Rolling Walk-Forward Analysis (per Architecture Report Section 5).
    Instead of a single IS/OOS split, uses rolling train/test windows.
    
    The outermost loop slides the WFA window forward:
      Window 1: Train[0..T], Test[T..T+S] → Discover P1, validate on Test
      Window 2: Train[step..T+step], Test[T+step..T+step+S] → Discover P2, validate
      ...
    The combined OOS equity curve is the TRUE strategy performance.
    """
    start_time = datetime.now()
    print(f"\n{'='*70}")
    print(f" ROLLING WALK-FORWARD ANALYSIS (per Architecture Report)")
    print(f"{'='*70}")
    
    # Config
    train_bars = getattr(cfg, 'WFA_TRAIN_BARS', 8000)
    test_bars = getattr(cfg, 'WFA_TEST_BARS', 2000)
    step_bars = getattr(cfg, 'WFA_STEP_BARS', 1000)
    window_size = train_bars + test_bars
    
    # Fetch data
    tf = current_config.get('timeframe', cfg.TIMEFRAME)
    df_full = fetch_raw_data(cfg.SYMBOL, tf, cfg.MAX_FETCH_LIMIT)
    if df_full is None or len(df_full) < window_size:
        print(f"   Not enough data for Rolling WFA (need {window_size}, have {len(df_full) if df_full is not None else 0})")
        return None
    
    total_bars = len(df_full)
    n_windows = max(1, (total_bars - window_size) // step_bars + 1)
    
    print(f"   Data: {total_bars} bars | Train: {train_bars} | Test: {test_bars} | Step: {step_bars}")
    print(f"   Windows: {n_windows}")
    
    # Accumulate OOS results
    oos_results = []
    window_params = []
    
    for w in range(n_windows):
        start_idx = w * step_bars
        train_end = start_idx + train_bars
        test_end = train_end + test_bars
        
        if test_end > total_bars:
            break
        
        df_train = df_full.iloc[start_idx:train_end].copy().reset_index(drop=True)
        df_test = df_full.iloc[train_end:test_end].copy().reset_index(drop=True)
        
        print(f"\n   Window {w+1}/{n_windows}: Train[{start_idx}:{train_end}] Test[{train_end}:{test_end}]")
        
        # Optimize on THIS window's training slice. Passing df is what makes
        # this a rolling analysis — without it, execute_optimization_logic
        # refetches the latest full dataset and every window optimizes on the
        # same data, then "validates" on a df_test that overlaps it.
        try:
            result = execute_optimization_logic(
                current_config,
                strategy_path=strategy_path,
                df=df_train
            )

            if result is None or result[0] is None or result[5] == -999:
                print(f"     No valid result for window {w+1}")
                continue
            
            best_params = result[0]
            
            # Validate on test data
            df_test_calc = df_test.copy()
            df_test_calc = add_indicators(df_test_calc, best_params)
            df_test_calc = generate_signals(df_test_calc, best_params)
            
            oos_bal, oos_wins, oos_trades, oos_mdd, _ = run_deep_backtest(df_test_calc, best_params)
            oos_wr = (oos_wins / oos_trades * 100) if oos_trades > 0 else 0
            oos_return = (oos_bal - getattr(cfg, 'START_BALANCE', 100.0)) / getattr(cfg, 'START_BALANCE', 100.0)
            
            oos_results.append({
                'window': w + 1,
                'balance': oos_bal,
                'wins': oos_wins,
                'trades': oos_trades,
                'mdd': oos_mdd,
                'win_rate': oos_wr,
                'return': oos_return
            })
            window_params.append(best_params)
            
            print(f"     OOS: Bal={oos_bal:.2f} | WR={oos_wr:.1f}% | MDD={oos_mdd*100:.1f}% | Ret={oos_return*100:+.1f}%")
            
        except Exception as e:
            print(f"     Window {w+1} error: {e}")
            continue
    
    # Aggregate results
    if oos_results:
        avg_return = sum(r['return'] for r in oos_results) / len(oos_results)
        avg_wr = sum(r['win_rate'] for r in oos_results) / len(oos_results)
        max_mdd = max(r['mdd'] for r in oos_results)
        profitable_windows = sum(1 for r in oos_results if r['return'] > 0)
        
        print(f"\n{'='*70}")
        print(f" ROLLING WFA SUMMARY")
        print(f"{'='*70}")
        print(f"   Windows Tested: {len(oos_results)}/{n_windows}")
        print(f"   Avg OOS Return: {avg_return*100:+.2f}%")
        print(f"   Avg Win Rate: {avg_wr:.1f}%")
        print(f"   Worst MDD: {max_mdd*100:.1f}%")
        print(f"   Profitable Windows: {profitable_windows}/{len(oos_results)} ({profitable_windows/len(oos_results)*100:.0f}%)")
        
        if profitable_windows / len(oos_results) >= 0.6:
            print(f"   Verdict: STRATEGY VALIDATED — Consistent OOS profitability")
        else:
            print(f"   Verdict: POTENTIAL OVERFITTING — Inconsistent OOS performance")
        print(f"{'='*70}\n")
        
        # Return the most recent window's params (most relevant to current market)
        if window_params:
            final_params = window_params[-1]
            final_oos = oos_results[-1]
            return final_params, final_oos['wins'], final_oos['trades'], final_oos['mdd'], final_oos['balance'], avg_return
    
    return None


def execute_smart_optimization(current_config, strategy_path=None):
    """
    Two-Phase Smart Optimization (Strategy A):
    Phase 1: Optimize Indicators (based on strategies.json) & Coarse Scan Filters.
    Phase 2: Use Best Indicators, Optimize Filters & Risk with Fine-Tuned Grids.
    FULLY MODULAR: Dynamically builds ranges from config.STRATEGY_PARAMS.
    """
    print("\n   [Smart Optimization] Starting Phase 1: Indicators & Model...")
    
    # 0. Identify Strategy & Load Search Space
    active_strat = current_config.get('active_strategy', 'standard')
    strat_space = getattr(cfg, 'STRATEGY_PARAMS', {}).get(active_strat, {})
    
    if not strat_space:
        print(f"   [Error] No STRATEGY_PARAMS defined for strategy '{active_strat}' in config.py.")
        return None

    # 1. Identify Indicator Parameters (Modular)
    indicator_param_names = get_indicator_params_from_json()
    
    # 2. Build Phase 1 Ranges
    # Logic: 
    #   - If Indicator Param: Use Dynamic Range (get_range) or full list.
    #   - If Filter Param: Use Default (First item) or current_config value.
    ranges_p1 = {}
    
    for param, space in strat_space.items():
        # Determine current value helper
        current_val = current_config.get(param)
        
        # Handle 'dynamic' type
        if isinstance(space, dict) and space.get('type') == 'dynamic':
            # Indicator param: create range around current val
            step = space.get('step', 2)
            ranges_p1[param] = get_range(current_val, step)
        elif isinstance(space, list):
            # List type
            if param in indicator_param_names:
                # Optimize fully in Phase 1
                ranges_p1[param] = space
            else:
                # Filter param: Fix to default (first item) or current config value if exists
                # We use set intersection to verify current_val is valid, else default
                val_to_use = current_val if current_val in space else space[0]
                ranges_p1[param] = [val_to_use]
        else:
             # Fallback for unexpected types
             ranges_p1[param] = [current_val]

    # Run Phase 1
    res_p1 = execute_optimization_logic(current_config, custom_ranges=ranges_p1, strategy_path=strategy_path)

    if not res_p1 or res_p1[0] is None:
        print("   [Smart Optimization] Phase 1 Failed. Returning None.")
        return None
        
    best_p1_params = res_p1[0] # Best params from Phase 1
    print(f"   [Smart Optimization] Phase 1 Done. Best Score: {res_p1[5]:.2f}")
    
    # 3. Build Phase 2 Ranges
    # Logic:
    #   - If Indicator Param: Fix to Best Result from Phase 1.
    #   - If Filter Param: Use Full Search Space (Grid).
    print("\n   [Smart Optimization] Starting Phase 2: Filters & Risk...")
    
    ranges_p2 = {}
    
    for param, space in strat_space.items():
        # Handle 'dynamic' type (Indicator params)
        if isinstance(space, dict) and space.get('type') == 'dynamic':
            # Fix to best result
            best_val = best_p1_params.get(param)
            ranges_p2[param] = [best_val]
        elif isinstance(space, list):
            # List type
            if param in indicator_param_names:
                # Fix to best result
                 best_val = best_p1_params.get(param)
                 ranges_p2[param] = [best_val]
            else:
                # Filter param: Use Full Grid
                ranges_p2[param] = space
        else:
             ranges_p2[param] = [current_config.get(param)]

    # Run Phase 2
    res_p2 = execute_optimization_logic(current_config, custom_ranges=ranges_p2, strategy_path=strategy_path)
    
    print(f"   [Smart Optimization] Phase 2 Done. Best Score: {res_p2[5]:.2f}")
    return res_p2
