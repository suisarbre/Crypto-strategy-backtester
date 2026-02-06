
# strategies/aggressive.py
from .base import BaseTradeLogic

class AggressiveLogic(BaseTradeLogic):
    """
    [공격형 전략]
    - 진입: 1 (Long), -1 (Short)
    - 스위칭: 반대 신호 발생 시 즉시 청산 후 진입
    - 부분 익절: 없음 (신호 0은 무시하고 포지션 유지)
    """
    def process_signal(self, state, price, signal, atr=0.0):
        logs = []
        
        if signal == 1:
            lev_pnl = self.get_pnl(state, price)
            
            if state.position == -1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
            
            if state.position == 0:
                state.open_position(1, price, atr)
                logs.append(f"🔥 [AGGRESSIVE LONG] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")
                
        elif signal == -1:
            lev_pnl = self.get_pnl(state, price)
            
            if state.position == 1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
                
            if state.position == 0:
                state.open_position(-1, price, atr)
                logs.append(f"🔥 [AGGRESSIVE SHORT] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")

        # 신호 0은 무시 (홀딩)
        
        return logs
