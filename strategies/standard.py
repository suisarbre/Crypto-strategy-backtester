
# strategies/standard.py
from .base import BaseTradeLogic

class StandardLogic(BaseTradeLogic):
    """
    [기본 전략]
    - 진입: 1 (Long), -1 (Short)
    - 스위칭: 반대 신호 발생 시 즉시 청산 후 진입
    - 부분 익절: 신호 0 발생 시 50% 부분 청산 (1회)
    """
    def process_signal(self, state, price, signal, atr=0.0):
        logs = []
        
        # [NEW] Trailing Stop Logic (Activated after Partial Exit)
        if state.partial_done:
            ts_mult = getattr(state.config, 'attr_trail_multiplier', 3.0) 
            # If not in config object, try global fallback or default
            ts_mult = state.config.get('atr_trail_multiplier', 3.0)
            
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
                
                # [NEW] Set Initial Trailing Stop to Breakeven (or Entry)
                # 안전하게 본절+@로 설정
                if state.position == 1:
                    state.trailing_stop_price = max(state.trailing_stop_price, state.avg_entry)
                else:
                    state.trailing_stop_price = min(state.trailing_stop_price, state.avg_entry)
                
                est_profit = (state.balance * 0.5) * lev_pnl
                msg = f"🌊 [Partial Exit] 50% Close @ {price} (ROI: {lev_pnl*100:.2f}% | ${est_profit:+.2f}) -> TS Active"
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
