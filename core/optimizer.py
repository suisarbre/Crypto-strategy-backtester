import itertools
from datetime import datetime
import sys
import config as cfg
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
from core.backtester import run_deep_backtest

def execute_optimization_logic(current_config):
    """
    현재 설정을 기반으로 주변 파라미터를 탐색하여 최적의 설정을 반환합니다.
    여러 전략(Available Strategies)을 모두 테스트하여 가장 좋은 전략과 파라미터를 찾습니다.
    """
    start_time = datetime.now()
    print(f"\n[{start_time.strftime('%H:%M')}] ⚙️ 전략 및 파라미터 정밀 최적화 시작...")
    
    # 1. 데이터 가져오기 (공통)
    df_raw_origin = fetch_raw_data(cfg.SYMBOL, cfg.TIMEFRAME, cfg.MAX_FETCH_LIMIT)
    if df_raw_origin is None: 
        return None, 0, 0, 0, 0
    
    # [NEW] 타임프레임 목록 가져오기
    timeframes_to_test = cfg.AVAILABLE_TIMEFRAMES if hasattr(cfg, 'AVAILABLE_TIMEFRAMES') else ['5m']
    strategies_to_test = cfg.AVAILABLE_STRATEGIES if hasattr(cfg, 'AVAILABLE_STRATEGIES') else ['standard']
    
    print(f"   >>> 테스트할 타임프레임: {timeframes_to_test}")
    print(f"   >>> 테스트할 전략 목록: {strategies_to_test}")

    # [WFA Logic]
    wfa_window = getattr(cfg, 'WFA_WINDOW_SIZE', 15000)
    train_ratio = getattr(cfg, 'WFA_TRAIN_RATIO', 0.7)

    # 1. Window Slicing (최근 N개만 사용)
    if len(df_raw_origin) > wfa_window:
        df_raw_origin = df_raw_origin.tail(wfa_window).copy().reset_index(drop=True)
    
    # 2. IS / OOS Split
    total_bars = len(df_raw_origin)
    oos_size = int(total_bars * (1.0 - train_ratio)) # 예: 30%
    min_is_size = 2000
    
    df_is = df_raw_origin
    df_oos = None
    
    if total_bars >= (min_is_size + oos_size):
        split_idx = total_bars - oos_size
        df_is = df_raw_origin.iloc[:split_idx].copy()
        df_oos = df_raw_origin.iloc[split_idx:].copy()
        print(f"\n🧩 [WFA Split] Window={total_bars} (Train Ratio={train_ratio})")
        print(f"   👉 In-Sample (Train): {len(df_is)} bars (0 ~ {split_idx})")
        print(f"   👉 Out-of-Sample (Test): {len(df_oos)} bars ({split_idx} ~ end)")
    else:
        print(f"\n⚠️ 데이터 부족으로 OOS 테스트 생략 (Total={total_bars})")
    
    # 최적화 로직에서 사용할 데이터프레임 교체
    # 루프 내에서 fetch_raw_data를 다시 부르지 않도록 주의해야 함.
    # 하지만 아래 루프는 config.TIMEFRAME이 아니라 'tf' 변수를 씀.
    # 즉, fetch_raw_data를 루프 안에서 다시 호출한다면 OOS 로직이 깨짐.
    # 현재 코드 구조상 루프 안에서 fetch_raw_data를 호출하지 않고 
    # 위에서 받은 df_raw_origin을 써야 하는데,
    # 만약 루프가 Multi-Timeframe이라면 위에서 받은 5m 데이터로 15m 최적화를 할 수 없음.
    # 따라서, 루프 안에서 데이터를 매번 새로 가져오는 구조라면...
    # OOS 로직을 루프 안으로 옮겨야 함.
    
    # 기존 코드 분석 결과:
    # df_raw_origin은 위에서 한 번 가져옴 (config.TIMEFRAME 기준).
    # 하지만 아래 반복문 for tf in timeframes_to_test: 에서
    # tf가 config.TIMEFRAME과 다르면 데이터를 다시 가져와야 함.
    # 현재 코드는 for tf in ... 로 돌면서 데이터를 '새로' 가져오지 않고
    # 기존 로직을 보면...
    pass # (This block replaces the initial setup to hint subsequent changes)

    # 전역 최고 기록 초기화
    global_best_score = -999
    global_best_params = current_config.copy()
    global_best_wins = 0
    global_best_trades = 0
    global_best_mdd = 0
    global_best_balance = getattr(cfg, 'START_BALANCE', 100.0)
    
    # === [Multi-Timeframe Loop] ===
    for tf in timeframes_to_test:
        print(f"\n⏳ 타임프레임 테스트 중: {tf}")
        
        # === [Multi-Strategy Loop] ===
        for strategy_name in strategies_to_test:
            print(f"   🔹 전략 테스트 중: {strategy_name.upper()} ({tf})")
            
            # 전략별 초기 설정
            local_config = current_config.copy()
            local_config['active_strategy'] = strategy_name 
            local_config['timeframe'] = tf # [NEW] 타임프레임 설정
            # local_config['max_bars_back'] = 3000 # [Removed] User config (25000) should prevail
            
            # 2. 초기화 (로컬 베스트)
            best_score = -999
            best_params = local_config.copy()
            best_wins = 0
            best_trades = 0
            best_mdd = 0
            best_balance = getattr(cfg, 'START_BALANCE', 100.0)
            
            # Coarse Scanning에서 사용할 바 갯수 리스트
            # 기존에는 [2000, 3000] 이었으나, 이제는 설정된 최대 갯수(약 25000)를 사용
            target_bars = local_config.get('max_bars_back', 3000)
            bars_list = [target_bars] 
            
            # 범위 설정 헬퍼 함수 (Float 지원)
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

            # 3. 파라미터 범위 설정
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
            
            # [Fix] 데이터 재로딩 (fetch logic handles caching internally, but we need fresh specific tf)
            # data_loader.fetch_raw_data uses 'fetch_OHLCV' which takes timeframe.
            # So we must call fetch for EACH timeframe loop.
            try:
                df_raw_tf = fetch_raw_data(cfg.SYMBOL, tf, cfg.MAX_FETCH_LIMIT)
                if df_raw_tf is None or len(df_raw_tf) < 500:
                    print(f"      Running out of data for {tf}, skipping...")
                    continue
                
                # [WFA OOS Split inside Loop]
                # 타임프레임별 데이터에 대해서도 동일 비율 적용
                df_optim = df_raw_tf
                if len(df_raw_tf) > wfa_window:
                    df_optim = df_raw_tf.tail(wfa_window).copy().reset_index(drop=True)

                current_total = len(df_optim)
                current_oos_size = int(current_total * (1.0 - train_ratio))
                
                if current_total >= (min_is_size + current_oos_size):
                     split_idx = current_total - current_oos_size
                     # 최적화에는 IS 데이터만 사용
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
                    # keys must match optimizer.cpp expectations: "rsi", "wt_ch", "wt_avg", "cci", "adx_len", "adx_th", "k", "lev"
                    ranges = {
                        "rsi": list(rsi_range),
                        "wt_ch": list(wt_ch_range),
                        "wt_avg": list(wt_avg_range),
                        "cci": list(cci_range),
                        "adx_len": list(adx_len_range),
                        "adx_th": list(adx_th_range),
                        "adx_th": list(adx_th_range),
                        "k": [12, 14, 16, 18, 20, 24], # [Dense Search]
                        "lev": list(leverage_range),
                        "sl_multiplier": list(sl_mult_range), # [NEW]
                        "ema_period": [80.0, 100.0, 120.0, 140.0, 160.0, 180.0, 200.0], # [Dense Search]
                        "use_ema_filter": [0.0, 1.0], # [Toggle]
                        "use_adx_filter": [0.0, 1.0]  # [Toggle]
                    }
                    
                    print(f"      🚀 C++ Coarse Scan ({bars} bars)...", end='\r')
                    
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
                        
                    sys.stdout.write(f"\r      🚀 C++ Coarse Scan Done! Best: {best_balance:.2f}          \n")

                else:
                    # Python Fallback skipped
                    pass

            # 5. [Fine-Tuning]
            if best_score == -999:
                print(f"      ⚠️ No valid results for {tf}/{strategy_name}.")
                continue
                
            print(f"      🔍 Fine-Tuning... (Best: {best_balance:.2f})")
            
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
                    "sl_multiplier": list(ft_sl_mult) # [NEW]
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
            
            print(f"      ✅ 완료! Result: {best_balance:.2f} (Lev: {best_params.get('leverage')}x)")
            
            # 전역 비교
            if best_score > global_best_score:
                global_best_score = best_score
                global_best_params = best_params.copy()
                global_best_wins = best_wins
                global_best_trades = best_trades
                global_best_mdd = best_mdd
                global_best_balance = best_balance

    # === [Final Report] ===
    print(f"\n🏆 최종 최적화 결과 (Multi-TF & Multi-Strategy) 🏆")
    sel_strat = global_best_params.get('active_strategy', 'UNKNOWN')
    sel_tf = global_best_params.get('timeframe', 'UNKNOWN')
    wr = (global_best_wins / global_best_trades * 100) if global_best_trades > 0 else 0
    print(f"   👉 선택된 전략: {sel_strat.upper()} @ {sel_tf}")
    print(f"   👉 성과: Bal {global_best_balance:.2f} | WR {wr:.1f}% ({global_best_wins}/{global_best_trades}) | MDD {global_best_mdd*100:.1f}%")
    print(f"   👉 레버리지: {global_best_params.get('leverage')}x")

    # [OOS Validation Report]
    if global_best_score != -999:
        try:
            print(f"\n🔮 [Out-of-Sample] 검증 결과 확인 중... (미래 5000개 데이터 테스트)")
            # Fetch full 15000 for winning timeframe
            best_tf = global_best_params.get('timeframe', '5m')
            df_full_final = fetch_raw_data(cfg.SYMBOL, best_tf, cfg.MAX_FETCH_LIMIT)
            
            if df_full_final is not None and len(df_full_final) >= 7000:
                oos_size_final = 5000
                warmup_buffer = 500 
                
                # OOS 시작점
                split_idx_final = len(df_full_final) - oos_size_final
                
                # Buffer 포함 시작점 (Warmup용)
                calc_start_idx = max(0, split_idx_final - warmup_buffer)
                
                # Buffer 포함하여 슬라이싱 -> 지표 계산 -> 앞부분(Buffer) 제거
                calc_start_idx = max(0, split_idx_final - warmup_buffer)
                
                # [WFA] 마지막 부분 사용
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
                    
                    print(f"   ✅ OOS 성과: Bal {oos_bal:.2f} | WR {oos_wr:.1f}% ({oos_trades} trades) | MDD {oos_mdd*100:.2f}%")

                    
                    if oos_bal > getattr(cfg, 'START_BALANCE', 100.0):
                        print("   🎉 축하합니다! 이 설정은 본 적 없는 미래 데이터에서도 수익을 냈습니다.")
                    else:
                        print("   ⚠️ 주의: 과거 데이터(IS)에서는 좋았으나, 미래 데이터(OOS)에서는 손실이 났습니다. 과최적화 가능성 있음.")
                else:
                    print("   ⚠️ OOS 데이터가 너무 적어 검증을 생략합니다.")
            else:
                print("   ⚠️ 데이터가 부족하여 OOS 검증을 수행지 못했습니다.")
        except Exception as e:
            print(f"   ⚠️ OOS 검증 중 오류 발생: {e}")


    return global_best_params, global_best_wins, global_best_trades, global_best_mdd, global_best_balance, global_best_score