
# trading_logic.py
import config as cfg

class BaseTradeLogic:
    """
    모든 매매 전략의 기본 클래스.
    process_signal을 구현하여 매매 신호에 따른 행동을 정의합니다.
    """
    def process_signal(self, state, price, signal):
        """
        신호를 처리하여 매매를 실행하고 로그를 반환합니다.
        
        Args:
            state (TradeStateManager): 거래 상태 관리자 인스턴스
            price (float): 현재 가격
            signal (int): 1 (Long), -1 (Short), 0 (Neutral)
            
        Returns:
            list[str]: 실행된 매매 로그 리스트
        """
        raise NotImplementedError("process_signal must be implemented")

class StandardLogic(BaseTradeLogic):
    """
    [기본 전략]
    - 진입: 1 (Long), -1 (Short)
    - 스위칭: 반대 신호 발생 시 즉시 청산 후 진입
    - 부분 익절: 신호 0 발생 시 50% 부분 청산 (1회)
    """
    def process_signal(self, state, price, signal):
        logs = []
        
        # 3-1. 포지션 진입/청산/스위칭
        if signal == 1:
            lev_pnl = self._get_pnl(state, price)
            
            if state.position == -1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
            
            if state.position == 0:
                state.open_position(1, price)
                logs.append(f"🚀 [LONG] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")
                
        elif signal == -1:
            lev_pnl = self._get_pnl(state, price)
            
            if state.position == 1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
                
            if state.position == 0:
                state.open_position(-1, price)
                logs.append(f"🚀 [SHORT] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")

        # 3-2. 부분 청산 (신호가 0이고 포지션 보유 중일 때)
        elif signal == 0:
            if state.position != 0 and not state.partial_done:
                lev_pnl = self._get_pnl(state, price)
                
                state.partial_done = True
                state.partial_pnl = lev_pnl
                
                # [Calc] 예상 수익금 계산 (절반만 청산하므로 balance의 50%에 대한 수익)
                est_profit = (state.balance * 0.5) * lev_pnl
                msg = f"🌊 [Partial Exit] 50% Close @ {price} (ROI: {lev_pnl*100:.2f}% | ${est_profit:+.2f})"
                logs.append(msg)
                
                # [Log] 부분 청산 기록
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

    def _get_pnl(self, state, price):
        if state.position == 0: return 0.0
        
        leverage = state.entry_leverage
        
        if state.position == 1:
            raw_pnl = (price - state.avg_entry) / state.avg_entry
        else:
            raw_pnl = (state.avg_entry - price) / state.avg_entry
            
        return raw_pnl * leverage

class AggressiveLogic(BaseTradeLogic):
    """
    [공격형 전략]
    - 진입: 1 (Long), -1 (Short)
    - 스위칭: 반대 신호 발생 시 즉시 청산 후 진입
    - 부분 익절: 없음 (신호 0은 무시하고 포지션 유지)
    """
    def process_signal(self, state, price, signal):
        logs = []
        
        # 3-1. 포지션 진입/청산/스위칭
        if signal == 1:
            lev_pnl = self._get_pnl(state, price)
            
            if state.position == -1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
            
            if state.position == 0:
                state.open_position(1, price)
                logs.append(f"🔥 [AGGRESSIVE LONG] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")
                
        elif signal == -1:
            lev_pnl = self._get_pnl(state, price)
            
            if state.position == 1:
                logs.append(state.close_position(price, "스위칭", lev_pnl))
                
            if state.position == 0:
                state.open_position(-1, price)
                logs.append(f"🔥 [AGGRESSIVE SHORT] 진입 @ {price} ({state.entry_leverage}x) | Size: ${state.balance:.2f}")

        # 신호 0은 무시 (홀딩)
        
        return logs

    def _get_pnl(self, state, price):
        # StandardLogic과 동일 (헬퍼 메서드)
        if state.position == 0: return 0.0
        leverage = state.entry_leverage
        if state.position == 1:
            raw_pnl = (price - state.avg_entry) / state.avg_entry
        else:
            raw_pnl = (state.avg_entry - price) / state.avg_entry
        return raw_pnl * leverage
