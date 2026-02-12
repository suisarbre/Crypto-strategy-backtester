import sys
import os
import config as cfg
from core.optimizer import execute_smart_optimization
import pandas as pd
from datetime import datetime

def main():
    print("=== Smart Optimization & Visualization Tool ===")
    
    # Load Initial Config
    current_config = {
        'symbol': cfg.SYMBOL,
        'timeframe': cfg.TIMEFRAME,
        'rsi_length': 14,
        'wt_channel_len': 10,
        'wt_avg_len': 21,
        'cci_length': 20,
        'adx_length': 14,
        'neighbors': 8,
        'adx_threshold': 25,
        'chop_threshold': 50.0,
        'leverage': 1, # Default
        'sl_multiplier': 0.0, # Default
        'ema_period': 140,
        'use_ema_filter': 1.0,
        'use_adx_filter': 1.0,
        'max_bars_back': 15000 # [Fix] Use full IS data (15000 * 0.7 = 10500)
    }
    
    # Inject Config Ranges if defined
    if hasattr(cfg, 'LEVERAGE_TEST_RANGE'):
        current_config['leverage_range'] = cfg.LEVERAGE_TEST_RANGE
        
    print(f"Starting Smart Optimization for {cfg.SYMBOL}...")
    
    start_time = datetime.now()
    result = execute_smart_optimization(current_config)
    end_time = datetime.now()
    
    if result is None:
        print("Optimization failed or returned no results.")
        return

    best_params, wins, trades, mdd, balance, score = result
    
    duration = end_time - start_time
    print(f"\n[Done] Optimization Completed in {duration}")
    print("\n[Result] Best Result:")
    print(f"   Balance: {balance:.2f} (Start: {getattr(cfg, 'START_BALANCE', 100)})")
    print(f"   Trades: {trades} (Wins: {wins})")
    print(f"   Win Rate: {(wins/trades*100):.1f}%" if trades > 0 else "   Win Rate: 0%")
    print(f"   MDD: {mdd*100:.2f}%")
    print(f"   Score: {score:.2f}")
    
    print("\n[Params] Best Parameters:")
    for k, v in best_params.items():
        print(f"   {k}: {v}")
        
    # Save to CSV
    record = {
        'timestamp': datetime.now().isoformat(),
        'duration': str(duration),
        'best_score': score,
        'balance': balance,
        'trades': trades,
        'wins': wins,
        'mdd': mdd,
        **best_params
    }
    
    df = pd.DataFrame([record])
    csv_file = 'optimizations.csv'
    if os.path.exists(csv_file):
        df.to_csv(csv_file, mode='a', header=False, index=False)
    else:
        df.to_csv(csv_file, mode='w', header=True, index=False)
        
    print(f"\nSaved result to {csv_file}")

    # Chart Generation Logic
    print("\n[Chart] Generating Visualization...")
    try:
        # 1. Fetch Full Data (No Split) or Validation Split? 
        # User said "based on the optimized strategy". Usually implies seeing the result.
        # Let's use the full IS+OOS data to show the whole picture.
        # max_bars_back is already set in best_params if we used the updated logic?
        # Actually best_params might not have it if it was injected in config.
        # We'll use the config's max_bars_back (15000).
        
        full_window = 15000
        df = pd.DataFrame() # Placeholder
        
        # We need to fetch data again or pass it out from optimizer? 
        # Optimizer doesn't return the DF. We must fetch.
        from data.data_loader import fetch_raw_data
        from analysis.indicators import add_indicators
        from analysis.signals import generate_signals
        
        target_tf = best_params.get('timeframe', cfg.TIMEFRAME)
        print(f"   Fetching 15000 bars for {target_tf}...")
        df = fetch_raw_data(cfg.SYMBOL, target_tf, full_window)
        
        if df is not None:
             # 2. Apply Indicators & Signals with BEST PARAMS
            print("   Applying Best Parameters...")
            # Ensure best_params has all necessary keys (some might be missing if not optimized)
            # We merge with current_config to be safe
            run_config = current_config.copy()
            run_config.update(best_params)
            
            df = add_indicators(df, run_config)
            df = generate_signals(df, run_config)
            
            # 3. Simulate Trades to get Markers
            # We need a Python-side logic to track trades and generate markers
            # core.backtester might not have a marker generator. Let's write a simple one here.
            
            from core.trade_state import TradeStateManager
            state = TradeStateManager(run_config)
            
            candle_data = []
            marker_data = []
            
            # Prepare Candle Data
            # Lightweight Charts expects seconds timestamp
            # df['timestamp'] is datetime?
            
            for i, row in df.iterrows():
                # Candle - Drop NaNs
                if pd.isna(row['open']) or pd.isna(row['close']):
                    continue
                    
                ts = int(row['timestamp'].timestamp())
                
                # Deduplicate check (lightweight charts crashes on dupes)
                if candle_data and candle_data[-1]['time'] == ts:
                    continue
                    
                candle_data.append({
                    'time': ts,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close'])
                })
                
                # Signal Processing
                price = row['close']
                signal = row['final_signal']
                atr = row.get('atr', 0.0)
                extras = {'supertrend_trend': row.get('supertrend_trend', 0)}
                
                # Capture State Before
                prev_pos = state.position
                prev_hist_len = len(state.trade_history)
                
                # Process
                logs = state.process_tick(price, signal=signal, current_atr=atr, **extras)
                
                # Capture State After
                curr_pos = state.position
                curr_hist_len = len(state.trade_history)
                
                # Marker Logic
                # 1. Entry
                if prev_pos == 0 and curr_pos != 0:
                    color = '#2196F3' if curr_pos > 0 else '#E91E63'
                    shape = 'arrowUp' if curr_pos > 0 else 'arrowDown'
                    text = 'LONG' if curr_pos > 0 else 'SHORT'
                    position = 'belowBar' if curr_pos > 0 else 'aboveBar'
                    marker_data.append({
                        'time': ts, 'position': position, 'color': color, 'shape': shape, 'text': text
                    })
                    
                # 2. Check for Partial Exit (Position didn't change to 0, but history increased)
                elif curr_hist_len > prev_hist_len:
                    last_trade = state.trade_history[-1]
                    if last_trade.get('type') == 'PARTIAL':
                        # Partial Exit Marker
                        # If Long (1), Partial Sell -> ArrowDown Above Bar
                        # If Short (-1), Partial Buy -> ArrowUp Below Bar
                        is_long = (prev_pos == 1)
                        color = '#FF9800' # Orange
                        shape = 'arrowDown' if is_long else 'arrowUp'
                        position = 'aboveBar' if is_long else 'belowBar'
                        text = f"50% ({last_trade['pnl']*100:.1f}%)"
                        
                        marker_data.append({
                            'time': ts, 'position': position, 'color': color, 'shape': shape, 'text': text
                        })

                # 3. Full Exit
                if prev_pos != 0 and curr_pos == 0:
                    pnl = 0.0
                    if state.trade_history:
                        pnl = state.trade_history[-1]['pnl']
                    color = '#4CAF50' if pnl > 0 else '#F44336'
                    shape = 'circle'
                    text = f"{pnl*100:.2f}%"
                    position = 'aboveBar' if prev_pos == 1 else 'belowBar'
                    marker_data.append({
                        'time': ts, 'position': position, 'color': color, 'shape': shape, 'text': text
                    })
            
            # 4. Inject into HTML
            with open('chart_template.html', 'r', encoding='utf-8') as f:
                template = f.read()
                
            stats_json = {
                'balance': state.balance,
                'start_balance': getattr(cfg, 'START_BALANCE', 100),
                'trades': state.trades,
                'win_rate': (state.wins / state.trades * 100) if state.trades > 0 else 0,
                'mdd': state.max_drawdown
            }
            
            import json
            html_content = template.replace('{{ CANDLE_DATA }}', json.dumps(candle_data))
            html_content = html_content.replace('{{ MARKER_DATA }}', json.dumps(marker_data))
            html_content = html_content.replace('{{ STATS_DATA }}', json.dumps(stats_json))
            
            out_file = 'optimization_result.html'
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            print(f"\n[Chart] Saved to {out_file}")
            print(f"👉 Open this file in your browser to see the chart!")
            
    except Exception as e:
        print(f"\n[Chart] Error generating chart: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
