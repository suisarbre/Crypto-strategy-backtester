# trade_state.py
import config as cfg
import strategies
import json
import os

class TradeStateManager:
    """
    모든 매매 상태와 로직을 관리하는 클래스.
    Trader(Live)와 Backtester에서 공통으로 사용.
    """
    def __init__(self, config=None, logger=None):
        self.config = config if config else cfg.CURRENT_CONFIG.copy()
        self.logger = logger # [NEW] Logger 주입
        self.logic = None # [Fix] Initialize before load_params
        
        # [WFA] 저장된 파라미터 로드
        self.load_params()
        
        # [NEW] 전략 로직 선택
        # config에 'active_strategy' 키가 있으면 사용, 없으면 cfg.ACTIVE_STRATEGY 사용
        strategy_name = self.config.get('active_strategy', cfg.ACTIVE_STRATEGIES[0] if hasattr(cfg, 'ACTIVE_STRATEGIES') else 'standard')
        # 혹시 AVAILABLE_STRATEGIES만 있고 active_strategy가 없을 경우 대비
        if not strategy_name: strategy_name = 'standard'
        
        self.logic = strategies.get_strategy(strategy_name)
        
        # 계좌 상태
        self.balance = getattr(cfg, 'START_BALANCE', 100.0)
        self.position = 0  # 0: None, 1: Long, -1: Short
        self.avg_entry = 0.0
        self.entry_leverage = 1 # 진입 시점 레버리지
        self.entry_atr = 0.0    # [NEW] 진입 시점 ATR
        
        # [History] 실제/백테스트 체결 내역 저장
        self.trade_history = []
        
        # 통계
        self.wins = 0
        self.trades = 0
        
        # 부분 청산 상태
        self.partial_done = False
        self.partial_pnl = 0.0
        self.trailing_stop_price = 0.0 # [NEW] Trailing Stop Price
        
        # 최대 낙폭 계산용
        # 최대 낙폭 계산용
        self.peak_balance = self.balance
        self.max_drawdown = 0.0
        
        # [NEW] 거래 일시정지 상태 (최적화 결과 손실 시 True)
        self.is_paused = False
        
        # [NEW] 사용자 수동 정지 (재시작 명령 전까지 절대 재개 안됨)
        self.is_manual_stop = False

    def get_active_timeframe(self):
        """
        [NEW] 현재 적용해야 할 타임프레임을 반환합니다.
        포지션이 있으면 진입 당시 타임프레임 유지, 없으면 현재 설정된 타임프레임 사용.
        """
        if self.position != 0 and self.entry_timeframe:
            return self.entry_timeframe
        return self.config.get('timeframe', '5m')

    def update_config(self, new_config):
        self.config = new_config
        
        # [NEW] 설정 변경 시 로직도 업데이트
        new_strat_name = self.config.get('active_strategy')
        if new_strat_name:
            # 현재 로직과 이름이 다르면 교체? (비교하기 어려우므로 그냥 재생성, 비용 낮음)
            # 단, logic 클래스 인스턴스 타입 비교 가능
            target_cls = strategies.STRATEGY_MAP.get(new_strat_name)
            if target_cls:
                if self.logic is None or not isinstance(self.logic, target_cls):
                    self.logic = target_cls()

    def process_tick(self, price, signal=None, current_atr=0.0, **kwargs):
        """
        매 틱(또는 캔들)마다 호출되어 상태를 업데이트합니다.
        
        Args:
            price (float): 현재 가격
            signal (int, optional): 전략 신호 (1: Long, -1: Short, 0: Neutral, None: 감시중)
            current_atr (float): 현재 ATR 값 (SL 계산 및 전략 전달용)
            
        Returns:
            list[str]: 발생한 이벤트 로그 메시지 리스트
        """
        logs = []
        sl_ratio = self.config.get('sl_ratio', cfg.SL_RATIO)
        
        # [ATR Dynamic SL Logic]
        # 최적화된 'sl_multiplier'가 있으면 ATR 기반 SL 우선 적용
        if self.config.get('USE_ATR_SL', False) and self.entry_atr > 0 and self.avg_entry > 0:
            sl_mult = self.config.get('sl_multiplier', 0.0)
            if sl_mult > 0:
                # Dynamic SL Ratio = (EntryATR * Multiplier) / EntryPrice
                sl_ratio = (self.entry_atr * sl_mult) / self.avg_entry
        
        # [Fix] 현재 포지션이 있으면 진입 시점의 레버리지 사용, 없으면 최신 설정 사용
        if self.position != 0:
            leverage = self.entry_leverage
        else:
            leverage = self.config.get('leverage', 1)
        
        # 1. PnL 계산 (포지션 있을 때만)
        lev_pnl = 0.0
        if self.position != 0:
            if self.position == 1:
                raw_pnl = (price - self.avg_entry) / self.avg_entry
            else: # -1
                raw_pnl = (self.avg_entry - price) / self.avg_entry
            lev_pnl = raw_pnl * leverage
            
        # 2. 리스크 관리 (손절 체크) - 전략과 무관하게 강제 수행
        if self.position != 0:
            if lev_pnl <= -sl_ratio:
                logs.append(self.close_position(price, "손절", lev_pnl))
                return logs # 손절되면 이번 틱 종료
                
        # 3. 전략 신호 처리 (위임)
        if signal is not None:
            # 전략 클래스에게 결정 위임 (ATR 전달)
            strategy_logs = self.logic.process_signal(self, price, signal, current_atr)
            logs.extend(strategy_logs)
                    
        # 4. MDD 업데이트
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        dd = (self.peak_balance - self.balance) / self.peak_balance
        if dd > self.max_drawdown:
            self.max_drawdown = dd
            
        return logs

    def open_position(self, side, price, atr=0.0):
        self.position = side
        self.avg_entry = price
        self.entry_atr = atr # [NEW]
        self.partial_done = False
        self.partial_pnl = 0.0
        # [NEW] 진입 시점의 레버리지 및 타임프레임 저장
        self.entry_leverage = self.config.get('leverage', 1)
        self.entry_timeframe = self.config.get('timeframe', '5m')
        self.trades += 1 
        
        # [Log] 진입 기록
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
        
        # 부분 청산 합성 PnL 계산
        if self.partial_done:
            final_pnl = (self.partial_pnl * 0.5) + (current_lev_pnl * 0.5)
            msg += "/Composite"
            
        # [Calc] 실현 손익금 계산 (수수료 제외 전 순수익)
        realized_profit_amt = self.balance * final_pnl
        
        fee = getattr(cfg, 'FEE_RATE', 0.001)
        self.balance *= (1 + final_pnl - fee) # 수수료 반영 후 잔고
        
        realized_pnl = final_pnl
        if final_pnl > 0: self.wins += 1
        
        old_pos = "LONG" if self.position == 1 else "SHORT"
        
        # [Log] 청산 기록
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

        # 상태 리셋
        self.position = 0
        self.partial_done = False
        self.partial_pnl = 0.0
        
        return f"청산 [{msg}]: {old_pos} @ {price} (ROI: {final_pnl*100:.2f}% | ${realized_profit_amt:+.2f}) -> Bal: {self.balance:.2f}"

    def manual_close_position(self, price, reason="Manual"):
        """
        [NEW] 수동 청산 기능
        """
        if self.position == 0:
            return None
            
        current_lev_pnl = 0.0
        # PnL 계산 (현재가 기준)
        if self.position == 1:
            lev_pnl = ((price - self.avg_entry) / self.avg_entry) * self.entry_leverage
        else:
            lev_pnl = ((self.avg_entry - price) / self.avg_entry) * self.entry_leverage
            
        msg = self.close_position(price, reason, lev_pnl)
        return msg

    def record_partial_exit(self, price, pnl_pct):
        """Standard/Hybrid Strategy에서 부분 청산 시 호출"""
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
        [WFA] 최적화된 파라미터를 JSON 파일로 저장합니다.
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
        [WFA] 저장된 파라미터가 있으면 로드하여 설정에 덮어씁니다.
        """
        try:
            path = getattr(cfg, 'PARAMS_FILE_PATH', 'best_params.json')
            if os.path.exists(path):
                with open(path, 'r') as f:
                    saved_params = json.load(f)
                    
                # 기존 config 업데이트 (덮어쓰기)
                self.config.update(saved_params)
                # print(f"📂 [System] Loaded best params from {path}") # [Silenced] User Request
                
                # 전략 로직 등 업데이트 필요 시 호출
                self.update_config(self.config)
        except Exception as e:
            print(f"⚠️ Failed to load params: {e}")
