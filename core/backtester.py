import numpy as np
import config as cfg
from core.trade_state import TradeStateManager

def run_deep_backtest(df, config):
    """
    TradeStateManager를 사용한 백테스팅 함수 (C++ 가속 지원)
    """
    # [C++ Integration]
    try:
        import cpp_engine
        use_cpp = True
    except ImportError:
        use_cpp = False

    if use_cpp:
        # Run C++ engine
        # Signature: prices, signals, atr, leverage, start_balance, sl_ratio, sl_multiplier, tp_ratio, fee
        prices = df['close'].values.astype(np.float64)
        signals = df['final_signal'].values.astype(np.int32)
        atr_vec = df['atr'].values.astype(np.float64)
        
        leverage = int(config.get('leverage', 1))
        sl_ratio = float(config.get('sl_ratio', 0.03)) 
        tp_ratio = float(config.get('tp_ratio', 0.8)) # Default or from config
        
        sl_mult = float(config.get('sl_multiplier', 0.0))
        start_bal = float(getattr(cfg, 'START_BALANCE', 100.0))
        fee_rate = float(getattr(cfg, 'FEE_RATE', 0.001))
        
        res = cpp_engine.fast_backtest(prices, signals, atr_vec, leverage, start_bal, sl_ratio, sl_mult, tp_ratio, fee_rate)
        
        return res['balance'], res['wins'], res['trades'], res['mdd'], res['balance']
    else:
        # Python Slow Backtest (Legacy)
        state = TradeStateManager(config)
        test_df = df.reset_index(drop=True)
        
        # 데이터프레임 순회
        for i in range(len(test_df) - 1):
            price = test_df['close'].iloc[i]
            signal = test_df['final_signal'].iloc[i]
            state.process_tick(price, signal)

        return state.balance, state.wins, state.trades, state.max_drawdown, state.balance

def run_backtest_with_markers(df, config, warmup=10):
    """
    Runs a backtest specifically to generate Lightweight-Charts markers.
    Returns: list of dicts [{'time': ts, 'position': 'aboveBar', 'color': '...', ...}]
    warmup (int): Number of initial bars to suppress entry markers (hides window-start artifacts).
    """
    state = TradeStateManager(config)
    
    # Ensure indicators are present (df should already have them, but safety check)
    # df should come in with 'final_signal', 'atr', etc.
    
    markers = []
    
    # We need to track standard TradeStateManager doesn't record 'Exit Reason' in a list,
    # so we will tap into the logs or state changes.
    
    # Local tracking
    last_pos = 0
    
    test_df = df.reset_index(drop=True)
    
    for i in range(len(test_df)):
        row = test_df.iloc[i]
        price = row['close']
        signal = row['final_signal']
        ts = int(row['timestamp'].timestamp())
        
        # Pass extras for Hybrid/Trend strategy
        current_atr = row['atr'] if 'atr' in row else 0.0
        st_trend = row['supertrend_trend'] if 'supertrend_trend' in row else 0
        extras = {'supertrend_trend': st_trend}
        
        # [Capture State Before]
        prev_pos = state.position
        prev_entry = state.avg_entry # Capture for PnL calc
        
        # Execute Logic
        logs = state.process_tick(price, signal=signal, current_atr=current_atr, extras=extras)
        
        # [Capture State After]
        curr_pos = state.position
        
        # Skip markers during warmup to prevent "Fake Entry at Window Start" artifacts
        if i < warmup:
            continue

        # 1. Entry Detected
        if prev_pos == 0 and curr_pos != 0:
            if curr_pos == 1:
                markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'LONG'})
            else:
                markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'SHORT'})
                
        # 2. Exit Detected (Complete Exit)
        elif prev_pos != 0 and curr_pos == 0:
            # Determine reason from logs if possible, or generic exit
            reason = 'Exit'
            color = '#f2c037' # Default Yellow
            
            # PnL Calculation
            pnl_pct = 0.0
            if prev_pos == 1: 
                pnl_pct = (price - prev_entry) / prev_entry
            else: 
                pnl_pct = (prev_entry - price) / prev_entry
                
            pnl_pct *= state.config.get('leverage', 1)
            pnl_str = f"({pnl_pct*100:+.2f}%)"
            
            if pnl_pct > 0: 
                color = '#21ba45' # Win
                reason = 'TP'
            else: 
                color = '#c10015' # Loss
                reason = 'SL'
                
            # Check logs for specific keywords
            for log in logs:
                if '손절' in log: reason = 'SL'
                
                # Trailing Stop (Standard)
                if 'TrailingStop' in log or 'TS' in log: 
                    reason = 'TS'
                    color = '#AB47BC' # Purple
                    
                # Hybrid / Trend Exit
                if 'SuperTrendExit' in log or 'RideEnd' in log:
                    reason = 'TrendEnd'
                    color = '#2962FF' # Blue
                    
                # Breakeven Floor
                if 'BreakevenFloor' in log:
                    reason = 'BE'
                    color = '#9E9E9E' # Gray
            
            full_text = f"{reason} {pnl_str}"
            markers.append({'time': ts, 'position': 'aboveBar' if prev_pos==1 else 'belowBar', 
                            'color': color, 'shape': 'circle', 'text': full_text})
                            
        # 3. Reversal (Flip)
        elif prev_pos != 0 and curr_pos != 0 and prev_pos != curr_pos:
            if curr_pos == 1:
                markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'Rev LONG'})
            else:
                markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'Rev SHORT'})

        # 4. Partial Exit Check (Position unchanged, but log contains Partial)
        elif prev_pos == curr_pos and prev_pos != 0:
            for log in logs:
                if 'Partial' in log or 'PARTIAL' in log:
                    # PnL Calc for Partial
                    if prev_pos == 1: pnl_pct = (price - prev_entry) / prev_entry
                    else: pnl_pct = (prev_entry - price) / prev_entry
                    pnl_pct *= state.config.get('leverage', 1)
                    
                    markers.append({'time': ts, 'position': 'aboveBar' if curr_pos==1 else 'belowBar', 
                                    'color': '#f2c037', 'shape': 'square', 'text': f'Partial ({pnl_pct*100:+.2f}%)'})
                    break # Only one marker per bar

    return markers