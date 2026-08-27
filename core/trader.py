from datetime import datetime
import threading
import sys
from data.data_loader import fetch_raw_data, fetch_current_price
from core.optimizer import execute_optimization_logic
import config as cfg

from core.trade_state import TradeStateManager
from core.logger import TradeLogger, OptimizationLogger

class TradingEngine:
    """
    [Refactor] Encapsulates the core trading loop logic:
    - Data Fetching
    - Delegating analysis to the caller's strategy

    Deliberately stateless: the engine holds NO strategy of its own. It used to,
    and because TradeStateManager holds one too, a strategy swap updated only the
    execution half while signal generation kept running the engine's original
    LorentzianStrategy. The strategy is now passed in per call so there is exactly
    one instance in play — TradeStateManager.logic. Do not add one back here.
    """

    def analyze_market(self, config, timeframe, strategy):
        """
        Fetches data, delegates to `strategy` for indicators/signals.
        Returns: (signal, price, atr, extras) or None if error/no data
        """
        # 1. Fetch Data
        df = fetch_raw_data(cfg.SYMBOL, timeframe, cfg.MAX_FETCH_LIMIT)
        if df is None: return None

        if len(df) > config.get('max_bars_back', 2000):
            df = df.tail(config.get('max_bars_back', 2000)).copy().reset_index(drop=True)

        # 2. Calculate Indicators (Strategy Delegate)
        df = strategy.calculate_indicators(df)

        # 3. Generate Signals (Strategy Delegate)
        df = strategy.generate_signals(df)

        # 5. Extract Results
        if 'final_signal' not in df.columns:
            sig = 0
        else:
            sig = df['final_signal'].iloc[-1]
            
        price = df['close'].iloc[-1]
        atr_val = df['atr'].iloc[-1] if 'atr' in df.columns else 0.0
        
        # Extras for reporting
        extras = {}
        if 'supertrend_trend' in df.columns:
            extras['supertrend_trend'] = df['supertrend_trend'].iloc[-1]
        
        return sig, price, atr_val, extras

class PaperTrader:
    def __init__(self):
        # [Log] Create logger
        self.trade_logger = TradeLogger('trades.csv')
        self.opt_logger = OptimizationLogger('optimizations.csv')
        
        # [Refactor] Delegate to state manager (inject logger)
        self.state = TradeStateManager(logger=self.trade_logger)
        self.is_optimizing = False
        
        # [Refactor] Trading Engine
        self.engine = TradingEngine()
        
        # [Threading] Lock for state synchronization
        self.lock = threading.Lock()

    def update_config(self, new_config):
        with self.lock:
            self.state.update_config(new_config)

    def run_optimization_thread(self):
        if self.is_optimizing: return
        self.is_optimizing = True
        
        from concurrent.futures import ThreadPoolExecutor
        config_copy = self.state.config.copy()
        
        def _process_waiter():
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(execute_optimization_logic, config_copy)
                    ret = future.result()
                    self._handle_optimization_result(ret)
            except Exception as e:
                print(f"Optimization Process Error: {e}")
            finally:
                self.is_optimizing = False
        
        t = threading.Thread(target=_process_waiter, daemon=True)
        t.start()
        
    def _handle_optimization_result(self, ret):
        try:
            # Optimization result is passed in as 'ret'
            if len(ret) == 6:
                new_params, w, t, m, b, s = ret
            else:
                new_params, w, t, m, b = ret
                s = 0.0 # fallback
            
            with self.lock:
                if new_params:
                    # [Multi-Timeframe] Apply 10% improvement rule
                    current_tf = self.state.config.get('timeframe', '5m')
                    new_tf = new_params.get('timeframe', current_tf)
                    
                    prev_score = cfg.PREVIOUS_BEST_SCORE
                    should_update = True
                    
                    # Score comparison (prev_score is -999 on first run)
                    if prev_score > -900:
                        # Apply strict threshold only when timeframe changes
                        if new_tf != current_tf:
                            improvement = (s - prev_score) / abs(prev_score) if prev_score != 0 else 0
                            threshold = getattr(cfg, 'TIMEFRAME_CHANGE_THRESHOLD', 0.10)
                            if improvement < threshold: # Improvement below threshold
                                print(f"\n\u270b [System] Timeframe change deferred: {current_tf} -> {new_tf}")
                                print(f"   (Score improvement {improvement*100:.1f}% < {threshold*100:.1f}% threshold not met)")
                                should_update = False
                    
                    if should_update:
                        self.state.update_config(new_params) # [Fix] Direct call to avoid lock re-entry
                        # [Session-Only] Don't persist to best_params.json;
                        # optimized values live in-memory for this session only.
                        cfg.PREVIOUS_BEST_SCORE = s # Update score
                        
                        start_bal = getattr(cfg, 'START_BALANCE', 100.0)
                        # [NEW] Pause trading if return is negative
                        if b < start_bal:
                            self.state.is_paused = True
                            print(f"\n⛔ Optimization predicts loss (Bal: {b:.2f}). Pausing until next optimization.")
                        else:
                            if self.state.is_paused:
                                print(f"\n▶️ Optimization predicts profit (Bal: {b:.2f}). Resuming trades.")
                            self.state.is_paused = False
                            
                        print(f"\n✅ Optimization applied! Lev: {self.state.config.get('leverage')}x | TF: {new_params.get('timeframe')} | Strat: {new_params.get('active_strategy')}")
                        
                        # [Debug] Print detailed parameters
                        print(f"   🔍 Details: K={new_params.get('neighbors')} | ADX_Th={new_params.get('adx_threshold')} | EMA={new_params.get('ema_period')}")
                        print(f"   🎛 Toggles: UseEMA={new_params.get('use_ema_filter')} | UseADX={new_params.get('use_adx_filter')}")
                        print(f"   📊 Features: RSI={new_params.get('rsi_length')} | WT={new_params.get('wt_channel_len')}/{new_params.get('wt_avg_len')} | CCI={new_params.get('cci_length')} | ADX={new_params.get('adx_length')}")
                    
                        # [Log] Record optimization result
                        self.opt_logger.log_optimization(
                            score=s,
                            balance=b,
                            win_rate=w/t if t > 0 else 0,
                            mdd=m,
                            params=new_params
                        )
                    else:
                        print("   -> Keeping existing settings.")
        except Exception as e:
            print(f"Error in optimization worker: {e}")
        finally:
            self.is_optimizing = False

    def monitor_position(self):
        """Print position status & current price every 1s (overwrite without newline)."""
        try:
            current_price = fetch_current_price(cfg.SYMBOL)
            if current_price is None: return

            # Current time
            now_str = datetime.now().strftime('%H:%M:%S')
            
            # Status string
            status = "RUNNING"
            if self.state.is_manual_stop: status = "MANUAL STOP"
            elif self.state.is_paused: status = "PAUSED"
            
            # [Lock] Acquire lock briefly for state query
            with self.lock:
                pos = self.state.position
                bal = self.state.balance
                entry = self.state.avg_entry
                lev = self.state.entry_leverage
                partial = self.state.partial_done
            
            if pos == 0:
                # Idle: current price | confirmed balance
                status_line = f"[{now_str}|{status}] Price: {current_price} | Bal: {bal:.2f}    "
            else:
                # In position: current price | PnL%($) | current balance | confirmed balance
                if pos == 1:
                    raw_pnl = (current_price - entry) / entry
                else:
                    raw_pnl = (entry - current_price) / entry
                
                lev_pnl = raw_pnl * lev
                
                # [Calc] Unrealized profit
                ratio = 0.5 if partial else 1.0
                unrealized_profit = (bal * ratio) * lev_pnl
                
                # Current estimated balance
                current_equity = bal + unrealized_profit
                
                pnl_str = f"{lev_pnl*100:+.2f}%"
                val_str = f"${unrealized_profit:+.2f}"
                partial_tag = " (Partial)" if partial else ""
                
                status_line = f"[{now_str}|{status}] Price: {current_price} | PNL: {pnl_str} ({val_str}) | CurBal: {current_equity:.2f} | FixBal: {bal:.2f}{partial_tag}    "
                
            sys.stdout.write(f"\r{status_line}")
            sys.stdout.flush()
            
        except Exception as e:
            # [Improvement] Error Handling
            sys.stdout.write(f"\rMonitor Error: {e}    ")
            sys.stdout.flush()

    def trade_job(self):
        # [Threading] Create worker thread to avoid blocking main thread
        t = threading.Thread(target=self._trade_job_logic, daemon=True)
        t.start()

    def _trade_job_logic(self):
        # [NEW] Skip logic if paused
        if self.state.is_paused or self.state.is_manual_stop:
            # print(f"\n🚫 [SKIP] Trading is paused.", end='')
            return

        current_price = fetch_current_price(cfg.SYMBOL)
        print(f"\n--- [Candle Close] {datetime.now().strftime('%H:%M:%S')} | Price: {current_price} ---")
        
        # [Multi-Timeframe] Fetch data using currently active timeframe
        active_tf = self.state.get_active_timeframe()
        
        # [Refactor] Delegate logic to TradingEngine.
        # state.logic is the single active strategy — see TradingEngine docstring.
        result = self.engine.analyze_market(self.state.config, active_tf, self.state.logic)
        if result is None: return
        
        sig, price, atr, extras = result
        
        # Critical Section: Execute trade and update state
        with self.lock:
            self.execute_trade_logic(sig, price, atr, extras)

    def execute_trade_logic(self, sig, price, atr=0.0, extras=None):
        try:
            # [Fix] Route through TradeStateManager.process_tick() so that
            # ALL risk management (SL, TP, trailing stop, breakeven, daily
            # loss limit, partial exit) is checked BEFORE strategy signals.
            # Previously this called strategy.process_signal() directly,
            # bypassing every exit/risk check.
            logs = self.state.process_tick(price, signal=sig, current_atr=atr, **(extras or {}))
            
            for log in logs:
                print(f" {log}")
                    
        except Exception as e:
            print(f"⚠️ Error executing trade logic: {e}")
        
    # ==================================================
    # [NEW] Manual Control Methods
    # ==================================================
    def kill_switch(self):
        with self.lock:
            self.state.is_manual_stop = True
            self.state.is_paused = True # Set both to True
            print(f"\n☠️ [KILL SWITCH] Force-stopping bot! Closing all positions.")
            
            # Close position if exists
            current_price = fetch_current_price(cfg.SYMBOL)
            if current_price:
                msg = self.state.manual_close_position(current_price, reason="Kill Switch")
                if msg: print(f"   -> {msg}")
            print("   -> Trading API calls blocked.")

    def manual_close(self):
        with self.lock:
            print(f"\n👋 [Manual Close] Force-closing current position. (Trading logic remains active)")
            current_price = fetch_current_price(cfg.SYMBOL)
            if current_price:
                msg = self.state.manual_close_position(current_price, reason="User Request")
                if msg: print(f"   -> {msg}")
                else: print("   -> No position currently held.")

    def resume_trading(self):
        with self.lock:
            self.state.is_manual_stop = False
            self.state.is_paused = False
            print(f"\n▶️ [Resume] Resuming trades. (Kill switch released)")