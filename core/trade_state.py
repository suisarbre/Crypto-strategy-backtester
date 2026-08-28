# trade_state.py
import config as cfg
import strategies
import json
import os
import threading

class TradeStateManager:
    """
    Manages all trading state and logic.
    Shared by Trader (live) and Backtester.
    """
    def __init__(self, config=None, logger=None):
        self.config = config if config else cfg.CURRENT_CONFIG.copy()
        self.logger = logger # [NEW] Logger injection
        self.logic = None # [Fix] Initialize before load_params
        
        # [Threading] Lock
        self.lock = threading.RLock()
        
        # [Session-Only] Don't load persisted params — start fresh each session.
        # self.load_params()
        
        # [NEW] Select strategy logic
        # Use 'active_strategy' from config, else the configured default.
        strategy_name = self.config.get('active_strategy') or getattr(cfg, 'ACTIVE_STRATEGY', 'standard')

        self.logic = strategies.get_strategy(strategy_name)
        
        # Account state
        self.balance = getattr(cfg, 'START_BALANCE', 100.0)
        self.position = 0  # 0: None, 1: Long, -1: Short
        self.avg_entry = 0.0
        self.entry_leverage = 1 # Leverage at entry
        self.entry_atr = 0.0    # [NEW] ATR at entry
        
        # [History] Store live/backtest trade records
        self.trade_history = []
        
        # Statistics
        self.wins = 0
        self.trades = 0
        
        # Partial exit state
        self.partial_done = False
        self.partial_pnl = 0.0
        self.trailing_stop_price = 0.0 # [NEW] Trailing Stop Price
        
        # Max drawdown tracking
        self.peak_balance = self.balance
        self.max_drawdown = 0.0
        
        # [NEW] Trading pause state (True when daily loss limit is hit)
        self.is_paused = False
        
        # [NEW] User manual stop (never resumes until explicit restart command)
        self.is_manual_stop = False

        # [Risk Management] Daily Loss Tracking
        self.daily_start_balance = self.balance
        self.last_trade_date = None # Track day change

    def get_active_timeframe(self):
        """
        [NEW] Returns the currently active timeframe.
        Uses the entry timeframe while in a position, otherwise uses the current config timeframe.
        """
        if self.position != 0 and self.entry_timeframe:
            return self.entry_timeframe
        return self.config.get('timeframe', '5m')

    def update_config(self, new_config):
        with self.lock:
            self.config = new_config
            
            # [NEW] Update strategy logic on config change.
            # Always rebuild: two JSON strategies share the JsonStrategyLogic class,
            # so an isinstance check would silently keep the previous rules loaded.
            # resolve_strategy_class raises on an unknown key rather than no-op'ing,
            # which previously left trades running under the old strategy (ADR-001).
            new_strat_name = self.config.get('active_strategy')
            if new_strat_name:
                self.logic = strategies.get_strategy(new_strat_name, base_config=self.config)

    def process_tick(self, price, signal=None, current_atr=0.0, timestamp=None, **kwargs):
        """
        Called on each tick (or candle) to update state.
        
        Args:
            price (float): Current price
            signal (int, optional): Strategy signal (1: Long, -1: Short, 0: Neutral, None: Monitoring)
            current_atr (float): Current ATR value (for SL calculation and strategy use)
            timestamp (int, optional): Current tick timestamp (required for backtest)
            
        Returns:
            list[str]: List of event log messages
        """
        logs = []
        
        with self.lock:
            sl_ratio = self.config.get('sl_ratio', cfg.SL_RATIO)
            
            # [ATR Dynamic SL Logic]
            # Use ATR-based SL when optimized 'sl_multiplier' is available
            if self.config.get('USE_ATR_SL', False) and self.entry_atr > 0 and self.avg_entry > 0:
                sl_mult = self.config.get('sl_multiplier', 0.0)
                if sl_mult > 0:
                    # Dynamic SL Ratio = (EntryATR * Multiplier) / EntryPrice
                    sl_ratio = (self.entry_atr * sl_mult) / self.avg_entry
            
            # [Fix] Use entry leverage if in position, otherwise use latest config
            if self.position != 0:
                leverage = self.entry_leverage
            else:
                leverage = self.config.get('leverage', 1)
            
            # 1. PnL calculation (only when in position)
            lev_pnl = 0.0
            if self.position != 0:
                if self.position == 1:
                    raw_pnl = (price - self.avg_entry) / self.avg_entry
                else: # -1
                    raw_pnl = (self.avg_entry - price) / self.avg_entry
                lev_pnl = raw_pnl * leverage
                
            # 2. Risk management (Stop Loss & Trailing Stop & Daily Loss)
            
            # [A] Daily Loss Check (Global)
            # If timestamp is provided, we are likely in backtest -> Use it for date calc
            # Measured on equity, and force-closes before pausing (ADR-004).
            logs.extend(self._check_daily_loss(price, timestamp))
            if self.is_paused:
                return logs # Trading paused, skip rest
                
            if self.position != 0:
                # [B] Centralized Trailing Stop & Breakeven
                # Only if strategy didn't signal exit yet (or we want to override)
                rs_log = self._check_risk_management(price, current_atr)
                if rs_log:
                    logs.append(rs_log)
                    return logs # Exit triggered
            
                # [C] Hard Stop Loss (Safety Net)
                if lev_pnl <= -sl_ratio:
                    logs.append(self.close_position(price, "stop_loss", lev_pnl))
                    return logs

                # [D] Take Profit & Partial Exit (matches C++ backtester)
                tp_ratio = float(self.config.get('tp_ratio', getattr(cfg, 'TP_RATIO', 0.99)))
                if lev_pnl >= tp_ratio:
                    if not self.partial_done:
                        # First TP hit → partial exit (50%), keep position open
                        self.partial_done = True
                        self.partial_pnl = lev_pnl
                        self.record_partial_exit(price, lev_pnl)
                        logs.append(
                            f"🔶 Partial TP @ {price} "
                            f"(PnL: {lev_pnl*100:.2f}% locked on 50%)"
                        )
                    else:
                        # Already partial → full TP exit
                        logs.append(self.close_position(price, "TakeProfit", lev_pnl))
                        return logs
                    
            # 3. Strategy signal processing (delegated)
            if signal is not None and self.position == 0: # Only entry if flat, or logic handles flip
                # Strategy might call close_position / open_position internally?
                # Ideally strategy returns actions, but current design calls state methods.
                # Since we hold the lock, it's safe.
                strategy_logs = self.logic.process_signal(self, price, signal, current_atr, extras=kwargs)
                logs.extend(strategy_logs)
            elif signal is not None and self.position != 0:
                # Exit signal processing
                strategy_logs = self.logic.process_signal(self, price, signal, current_atr, extras=kwargs)
                logs.extend(strategy_logs)
                        
            # 4. MDD update
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            dd = (self.peak_balance - self.balance) / self.peak_balance
            if dd > self.max_drawdown:
                self.max_drawdown = dd
            
        return logs

    def unrealized_pnl(self, price):
        """
        [Risk] Leveraged PnL of the open position at `price`, as a fraction of
        balance. Returns 0.0 when flat. Mirrors PaperTrader.monitor_position().
        """
        if self.position == 0 or self.avg_entry <= 0:
            return 0.0

        if self.position == 1:
            raw_pnl = (price - self.avg_entry) / self.avg_entry
        else:
            raw_pnl = (self.avg_entry - price) / self.avg_entry

        return raw_pnl * self.entry_leverage

    def equity(self, price):
        """[Risk] Balance plus unrealized PnL — half size after a partial exit."""
        lev_pnl = self.unrealized_pnl(price)
        if lev_pnl == 0.0:
            return self.balance

        size_ratio = 0.5 if self.partial_done else 1.0
        return self.balance + (self.balance * size_ratio * lev_pnl)

    def _check_daily_loss(self, current_price, timestamp=None):
        """
        [Risk] Check if daily loss limit is hit, measured on mark-to-market
        equity rather than realized balance (ADR-004).

        Force-closes any open position before pausing: process_tick() returns
        immediately once is_paused is set, so pausing without closing would
        strand the position with every downstream guard disabled.

        Resets daily_start_balance and clears the pause on day change.
        timestamp: Unix timestamp (int) or None. If None, uses system date.

        Returns: list[str] of event logs (may include a forced close).
        """
        import datetime

        logs = []

        if timestamp:
            current_date = datetime.datetime.fromtimestamp(timestamp).date()
            is_backtest = True
        else:
            current_date = datetime.date.today()
            is_backtest = False

        # Day Change Reset. Auto-resume is what makes this a *daily* limit rather
        # than a one-shot kill switch; is_manual_stop is deliberately untouched.
        if self.last_trade_date != current_date:
            self.last_trade_date = current_date
            self.daily_start_balance = self.balance
            if self.is_paused:
                self.is_paused = False
                logs.append("[RISK] New trading day — daily loss pause lifted.")

        if self.daily_start_balance <= 0 or self.is_paused:
            return logs

        # Mark to market: an open losing position counts toward the limit.
        current_equity = self.equity(current_price)
        loss_pct = (self.daily_start_balance - current_equity) / self.daily_start_balance
        limit = getattr(cfg, 'DAILY_LOSS_LIMIT', 0.05)

        if loss_pct < limit:
            return logs

        # Terminate: realize the position first, then pause.
        if self.position != 0:
            lev_pnl = self.unrealized_pnl(current_price)
            logs.append(self.close_position(current_price, "DailyLossLimit", lev_pnl))

        self.is_paused = True
        msg = f"[RISK] [STOP] Daily Loss Limit Hit (-{loss_pct*100:.1f}% equity). Trading Paused."
        logs.append(msg)
        if not is_backtest:
            print(f"\n{msg}")

        return logs

    def _check_risk_management(self, price, atr):
        """
        [Risk] Centralized Trailing Stop & Breakeven Logic.
        Returns log string if exit occurred, else None.
        """
        if self.position == 0: return None
        
        # Configs
        use_ts = getattr(cfg, 'USE_TRAILING_STOP', False)
        use_be = getattr(cfg, 'USE_BREAKEVEN', False)
        
        # PnL Calc
        if self.position == 1:
            raw_pnl = (price - self.avg_entry) / self.avg_entry
        else:
            raw_pnl = (self.avg_entry - price) / self.avg_entry
            
        # 1. Trailing Stop
        if use_ts:
            activation = getattr(cfg, 'TS_ACTIVATION', 0.02)
            callback = getattr(cfg, 'TS_CALLBACK', 0.01)
            
            if raw_pnl >= activation:
                # Set/Update High Watermark Price for TS
                if self.trailing_stop_price == 0:
                     # First activation
                     if self.position == 1: self.trailing_stop_price = price * (1 - callback)
                     else: self.trailing_stop_price = price * (1 + callback)
                else:
                    # Trailing Logic
                    if self.position == 1:
                        new_sl = price * (1 - callback)
                        if new_sl > self.trailing_stop_price: self.trailing_stop_price = new_sl
                    else:
                        new_sl = price * (1 + callback)
                        if new_sl < self.trailing_stop_price: self.trailing_stop_price = new_sl
                        
            # Check Exit
            if self.trailing_stop_price > 0:
                triggered = False
                if self.position == 1 and price < self.trailing_stop_price: triggered = True
                elif self.position == -1 and price > self.trailing_stop_price: triggered = True
                
                if triggered:
                    lev_pnl = raw_pnl * self.entry_leverage
                    return self.close_position(price, "TrailingStop", lev_pnl)

        # 2. Breakeven
        if use_be:
            be_trigger = getattr(cfg, 'BE_TRIGGER', 0.015)
            be_offset = getattr(cfg, 'BE_OFFSET', 0.002)
            
            if raw_pnl >= be_trigger:
                # We don't have a specific 'BE' state, but we can use Trailing Stop price as BE floor
                # If TS is not active or BE level is better than TS
                be_price = 0
                if self.position == 1: be_price = self.avg_entry * (1 + be_offset)
                else: be_price = self.avg_entry * (1 - be_offset)
                
                # Update TS price to at least BE
                if self.position == 1:
                    if self.trailing_stop_price < be_price: self.trailing_stop_price = be_price
                else:
                     if self.trailing_stop_price == 0 or self.trailing_stop_price > be_price: 
                        self.trailing_stop_price = be_price
                        
        return None

    def open_position(self, side, price, atr=0.0):
        self.position = side
        self.avg_entry = price
        self.entry_atr = atr # [NEW]
        self.partial_done = False
        self.partial_pnl = 0.0
        # [NEW] Save leverage and timeframe at entry
        self.entry_leverage = self.config.get('leverage', 1)
        self.entry_timeframe = self.config.get('timeframe', '5m')
        self.trades += 1 
        
        # [Log] Record entry
        if self.logger:
            self.logger.log_trade(
                event="ENTRY",
                symbol=self.config.get('symbol', 'UNKNOWN'),
                side="LONG" if side == 1 else "SHORT",
                price=price,
                pnl=0,
                balance=self.balance,
                leverage=self.entry_leverage,
                config=self.config
            )

    def close_position(self, price, msg, current_lev_pnl):
        final_pnl = current_lev_pnl
        
        # Composite PnL calculation for partial exits
        if self.partial_done:
            final_pnl = (self.partial_pnl * 0.5) + (current_lev_pnl * 0.5)
            msg += "/Composite"
            
        # [Calc] Realized profit amount (before fees)
        realized_profit_amt = self.balance * final_pnl
        
        fee = getattr(cfg, 'FEE_RATE', 0.001)
        leverage_fee = fee * self.entry_leverage  # Scale fee with leverage (matches C++ backtester)
        self.balance *= (1 + final_pnl - leverage_fee) # Balance after fees
        
        realized_pnl = final_pnl
        if final_pnl > 0: self.wins += 1
        
        old_pos = "LONG" if self.position == 1 else "SHORT"
        
        # [Log] Record exit
        if self.logger:
            self.logger.log_trade(
                event=f"EXIT ({msg})",
                symbol=self.config.get('symbol', 'UNKNOWN'),
                side=old_pos,
                price=price,
                pnl=realized_pnl,
                balance=self.balance,
                leverage=self.entry_leverage,
                config=self.config
            )

        # Reset state
        self.position = 0
        self.partial_done = False
        self.partial_pnl = 0.0
        self.trailing_stop_price = 0.0 # [Fix] Reset TS
        
        return f"Close [{msg}]: {old_pos} @ {price} (ROI: {final_pnl*100:.2f}% | ${realized_profit_amt:+.2f}) -> Bal: {self.balance:.2f}"

    def manual_close_position(self, price, reason="Manual"):
        """
        [NEW] Manual close position
        """
        if self.position == 0:
            return None
            
        current_lev_pnl = 0.0
        # PnL calculation (at current price)
        if self.position == 1:
            lev_pnl = ((price - self.avg_entry) / self.avg_entry) * self.entry_leverage
        else:
            lev_pnl = ((self.avg_entry - price) / self.avg_entry) * self.entry_leverage
            
        msg = self.close_position(price, reason, lev_pnl)
        return msg

    def record_partial_exit(self, price, pnl_pct):
        """Called on partial exit from Standard/Hybrid Strategy"""
        import time
        self.trade_history.append({
            'time': int(time.time()),
            'type': 'PARTIAL',
            'side': 'LONG' if self.position == 1 else 'SHORT',
            'price': price,
            'pnl': pnl_pct,
            'desc': 'Partial'
        })

    def save_params(self, params):
        """
        [WFA] Saves optimized parameters to a JSON file.
        """
        try:
            path = getattr(cfg, 'PARAMS_FILE_PATH', 'best_params.json')
            with open(path, 'w') as f:
                json.dump(params, f, indent=4)
            print(f"💾 [System] Best params saved to {path}")
        except Exception as e:
            print(f"⚠️ Failed to save params: {e}")

    def load_params(self):
        """
        [WFA] Loads saved parameters from file and applies them to config.
        """
        try:
            path = getattr(cfg, 'PARAMS_FILE_PATH', 'best_params.json')
            if os.path.exists(path):
                with open(path, 'r') as f:
                    saved_params = json.load(f)
                    
                # Update existing config (overwrite)
                self.config.update(saved_params)
                # print(f"📂 [System] Loaded best params from {path}") # [Silenced] User Request
                
                # Re-run update_config if strategy logic needs refreshing
                self.update_config(self.config)
        except Exception as e:
            print(f"⚠️ Failed to load params: {e}")
