
# strategies/standard.py
from .base import BaseTradeLogic

class StandardLogic(BaseTradeLogic):
    """
    [기본 전략]
    - 진입: 1 (Long), -1 (Short)
    - 스위칭: 반대 신호 발생 시 즉시 청산 후 진입
    - 부분 익절: 신호 0 발생 시 50% 부분 청산 (1회)
    """
    def process_signal(self, state, price, signal, atr=0.0, extras=None):
        logs = []
        if extras is None: extras = {}
        
        # [NEW] Check Config for Hybrid Strategy
        use_hybrid = state.config.get('USE_HYBRID_EXIT', False)
        
        # [NEW] Trailing Stop / Hybrid Logic (Activated after Partial Exit)
        if state.partial_done:
            
            # --- Option A: Hybrid Strategy (SuperTrend Exit) ---
            if use_hybrid and 'supertrend_trend' in extras:
                current_trend = extras['supertrend_trend'] # 1: Up, -1: Down
                
                # 1. Check Breakeven Floor (Safety First)
                floor_hit = False
                if state.position == 1: # Long
                    if price <= state.avg_entry: # Hit Entry
                        floor_hit = True
                elif state.position == -1: # Short
                    if price >= state.avg_entry: # Hit Entry
                        floor_hit = True
                        
                if floor_hit:
                    lev_pnl = self.get_pnl(state, price)
                    logs.append(state.close_position(price, "BreakevenFloor", lev_pnl))
                    return logs

                # 2. Check Trend Reversal (The "Ride" Logic)
                trend_reversal = False
                if state.position == 1 and current_trend == -1: # Long but Trend turned Down
                    trend_reversal = True
                elif state.position == -1 and current_trend == 1: # Short but Trend turned Up
                    trend_reversal = True
                    
                if trend_reversal:
                    lev_pnl = self.get_pnl(state, price)
                    logs.append(state.close_position(price, "SuperTrendExit", lev_pnl))
                    return logs

            # --- Option B: Standard ATR Trailing Stop ---
            else:
                # [Fix] Use 'sl_multiplier' (optimized) as default if 'atr_trail_multiplier' is not explicitly set separate.
                # This ensures consistency with C++ Backtester which uses sl_multiplier for both.
                fallback_mult = state.config.get('sl_multiplier', 3.0)
                if fallback_mult <= 0: fallback_mult = 3.0
                
                ts_mult = state.config.get('atr_trail_multiplier', fallback_mult)
                
                # 1. Update Trailing Stop Price
                if state.position == 1: # Long
                    new_ts = price - (atr * ts_mult)
                    # Trail Up Only
                    if new_ts > state.trailing_stop_price:
                        state.trailing_stop_price = new_ts
                    
                    # Check Hit
                    if price <= state.trailing_stop_price:
                        lev_pnl = self.get_pnl(state, price)
                        logs.append(state.close_position(price, "TrailingStop", lev_pnl))
                        return logs
                        
                elif state.position == -1: # Short
                    new_ts = price + (atr * ts_mult)
                    # Trail Down Only
                    if state.trailing_stop_price == 0 or new_ts < state.trailing_stop_price:
                        state.trailing_stop_price = new_ts
                        
                    # Check Hit
                    if price >= state.trailing_stop_price:
                        lev_pnl = self.get_pnl(state, price)
                        logs.append(state.close_position(price, "TrailingStop", lev_pnl))
                        return logs

        # 3-1. 포지션 진입/청산/스위칭
        if signal == 1:
            lev_pnl = self.get_pnl(state, price)
            
            if state.position == -1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
                # [Restore] No return here -> Immediate Switch
            
            if state.position == 0:
                state.open_position(1, price, atr)
                # Init TS (Breakeven or loose)
                state.trailing_stop_price = price - (atr * 3.0) 
                logs.append(f"🚀 [LONG] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f} (Standard)")
                
        elif signal == -1:
            lev_pnl = self.get_pnl(state, price)
            
            if state.position == 1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
                # [Restore] No return here -> Immediate Switch
                
            if state.position == 0:
                state.open_position(-1, price, atr)
                state.trailing_stop_price = price + (atr * 3.0)
                logs.append(f"🚀 [SHORT] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f} (Standard)")

        # 3-2. 부분 청산 (신호가 0이고 포지션 보유 중일 때)
        elif signal == 0:
            if state.position != 0 and not state.partial_done:
                lev_pnl = self.get_pnl(state, price)
                
                state.partial_done = True
                state.partial_pnl = lev_pnl
                
                # [History]
                try:
                    state.record_partial_exit(price, lev_pnl)
                except AttributeError: pass
                
                # [Match C++] Reset Trailing Stop & Secure Breakeven
                # C++ logic: 
                # trailing_stop_price = price - (current_atr * sl_multiplier);
                # if (trailing_stop_price < avg_entry) trailing_stop_price = avg_entry;
                
                ts_mult = state.config.get('sl_multiplier', 3.0)
                if ts_mult <= 0: ts_mult = 3.0
                
                if state.position == 1:
                    new_ts = price - (atr * ts_mult)
                    state.trailing_stop_price = max(new_ts, state.avg_entry)
                elif state.position == -1:
                    new_ts = price + (atr * ts_mult)
                    state.trailing_stop_price = min(new_ts, state.avg_entry)
                
                est_profit = (state.balance * 0.5) * lev_pnl
                msg = f"🌊 [Partial Exit] 50% Close @ {price} (ROI: {lev_pnl*100:.2f}% | ${est_profit:+.2f}) -> TS Reset to {state.trailing_stop_price:.2f}"
                logs.append(msg)
                
                if state.logger:
                    state.logger.log_trade(
                        event="PARTIAL_EXIT",
                        symbol=state.config.get('symbol', 'UNKNOWN'),
                        side="LONG" if state.position == 1 else "SHORT",
                        price=price,
                        pnl=lev_pnl * 0.5,
                        balance=state.balance,
                        leverage=state.entry_leverage,
                        config=state.config
                    )
        
        return logs
