
# strategies/base.py
from abc import ABC, abstractmethod

class BaseTradeLogic(ABC):
    """
    모든 매매 전략의 기본 추상 클래스.
    """
    @abstractmethod
    def process_signal(self, state, price, signal, atr=0.0):
        """
        신호를 처리하여 매매를 실행하고 로그를 반환합니다.
        
        Args:
            state (TradeStateManager): 거래 상태 관리자 인스턴스
            price (float): 현재 가격
            signal (int): 1 (Long), -1 (Short), 0 (Neutral)
            atr (float): 현재 ATR (Volatility)
            
        Returns:
            list[str]: 실행된 매매 로그 리스트
        """
        pass

    def get_pnl(self, state, price):
        """
        공통 PnL 계산 헬퍼
        """
        if state.position == 0: return 0.0
        
        leverage = state.entry_leverage
        
        if state.position == 1:
            raw_pnl = (price - state.avg_entry) / state.avg_entry
        else:
            raw_pnl = (state.avg_entry - price) / state.avg_entry
            
        return raw_pnl * leverage
