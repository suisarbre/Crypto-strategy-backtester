
# trader.py
import time
from datetime import datetime
import threading
import sys
from data.data_loader import fetch_raw_data, fetch_current_price
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
from core.optimizer import execute_optimization_logic
import config as cfg

from core.trade_state import TradeStateManager
from core.logger import TradeLogger, OptimizationLogger

class PaperTrader:
    def __init__(self):
        # [Log] 로거 생성
        self.trade_logger = TradeLogger('trades.csv')
        self.opt_logger = OptimizationLogger('optimizations.csv')
        
        # [Refactor] 상태 관리자 위임 (로거 주입)
        self.state = TradeStateManager(logger=self.trade_logger)
        self.is_optimizing = False
        
        # [Threading] 상태 동기화를 위한 Lock
        self.lock = threading.Lock()

    def update_config(self, new_config):
        with self.lock:
            self.state.update_config(new_config)

    def run_optimization_thread(self):
        if self.is_optimizing: return
        t = threading.Thread(target=self._optimize_worker, daemon=True)
        t.start()
        
    def _optimize_worker(self):
        self.is_optimizing = True
        try:
            # 최적화 수행
            # [Fix] score(s) 추가 반환
            ret = execute_optimization_logic(self.state.config.copy())
            if len(ret) == 6:
                new_params, w, t, m, b, s = ret
            else:
                new_params, w, t, m, b = ret
                s = 0.0 # fallback
            
            with self.lock:
                if new_params:
                    # [Multi-Timeframe] 10% 향상 룰 적용
                    current_tf = self.state.config.get('timeframe', '5m')
                    new_tf = new_params.get('timeframe', current_tf)
                    
                    prev_score = cfg.PREVIOUS_BEST_SCORE
                    should_update = True
                    
                    # 점수 비교 (첫 실행 시 prev_score는 -999)
                    if prev_score > -900:
                        # 타임프레임이 변경되는 경우에만 엄격한 기준 적용
                        if new_tf != current_tf:
                            improvement = (s - prev_score) / abs(prev_score) if prev_score != 0 else 0
                            threshold = getattr(cfg, 'TIMEFRAME_CHANGE_THRESHOLD', 0.10)
                            if improvement < threshold: # 설정된 퍼센트 미만 향상
                                print(f"\n✋ [System] 타임프레임 변경 보류: {current_tf} -> {new_tf}")
                                print(f"   (점수 향상 {improvement*100:.1f}% < {threshold*100:.1f}% 기준 미달)")
                                should_update = False
                    
                    if should_update:
                        self.state.update_config(new_params) # [Fix] lock 재진입 방지 위해 직접 호출
                        self.state.save_params(new_params)   # [WFA] 파라미터 저장
                        cfg.PREVIOUS_BEST_SCORE = s # 점수 갱신
                        
                        start_bal = getattr(cfg, 'START_BALANCE', 100.0)
                        # [NEW] 수익률이 마이너스면 거래 중단
                        if b < start_bal:
                            self.state.is_paused = True
                            print(f"\n⛔ 최적화 결과 손실 예상 (Bal: {b:.2f}). 다음 최적화까지 거래를 일시 정지합니다.")
                        else:
                            if self.state.is_paused:
                                print(f"\n▶️ 최적화 결과 수익 예상 (Bal: {b:.2f}). 거래를 재개합니다.")
                            self.state.is_paused = False
                            
                        print(f"\n✅ 최적화 적용 완료! Lev: {self.state.config.get('leverage')}x | TF: {new_params.get('timeframe')} | Strat: {new_params.get('active_strategy')}")
                        
                        # [Debug] 상세 파라미터 출력
                        print(f"   🔍 Details: K={new_params.get('neighbors')} | ADX_Th={new_params.get('adx_threshold')} | EMA={new_params.get('ema_period')}")
                        print(f"   🎛 Toggles: UseEMA={new_params.get('use_ema_filter')} | UseADX={new_params.get('use_adx_filter')}")
                        print(f"   📊 Features: RSI={new_params.get('rsi_length')} | WT={new_params.get('wt_channel_len')}/{new_params.get('wt_avg_len')} | CCI={new_params.get('cci_length')} | ADX={new_params.get('adx_length')}")
                    
                        # [Log] 최적화 결과 기록
                        self.opt_logger.log_optimization(
                            score=s,
                            balance=b,
                            win_rate=w/t if t > 0 else 0,
                            mdd=m,
                            params=new_params
                        )
                    else:
                        print("   -> 기존 설정을 유지합니다.")

        except Exception as e:
            print(f"Error in optimization worker: {e}")
        finally:
            self.is_optimizing = False

    def monitor_position(self):
        """
        [Realtime] 1초마다 포지션 상태 및 현재가 출력 (줄바꿈 없이 갱신)
        """
        try:
            current_price = fetch_current_price(cfg.SYMBOL)
            if current_price is None: return

            # 현재 시간
            now_str = datetime.now().strftime('%H:%M:%S')
            
            # 상태 문자열
            status = "RUNNING"
            if self.state.is_manual_stop: status = "MANUAL STOP"
            elif self.state.is_paused: status = "PAUSED"
            
            # [Lock] 상태 조회 시에는 락 필요 (잠깐)
            with self.lock:
                pos = self.state.position
                bal = self.state.balance
                entry = self.state.avg_entry
                lev = self.state.entry_leverage
                partial = self.state.partial_done
            
            if pos == 0:
                # 대기 상태: 현재가 | 확정 잔고
                sys.stdout.write(f"\r[{now_str}|{status}] Price: {current_price} | Bal: {bal:.2f}    ")
            else:
                # 포지션 보유 상태: 현재가 | PNL%($) | 현재 잔고 | 확정 잔고
                if pos == 1:
                    raw_pnl = (current_price - entry) / entry
                else:
                    raw_pnl = (entry - current_price) / entry
                
                lev_pnl = raw_pnl * lev
                
                # [Calc] 평가 수익금
                ratio = 0.5 if partial else 1.0
                unrealized_profit = (bal * ratio) * lev_pnl
                
                # 현재 추정 잔고
                current_equity = bal + unrealized_profit
                
                pnl_str = f"{lev_pnl*100:+.2f}%"
                val_str = f"${unrealized_profit:+.2f}"
                partial_tag = " (Partial)" if partial else ""
                
                sys.stdout.write(f"\r[{now_str}|{status}] Price: {current_price} | PNL: {pnl_str} ({val_str}) | CurBal: {current_equity:.2f} | FixBal: {bal:.2f}{partial_tag}    ")
                
            sys.stdout.flush()
            
        except Exception as e:
            pass

    def trade_job(self):
        # [Threading] 메인 스레드 차단을 방지하기 위해 작업 스레드 생성
        t = threading.Thread(target=self._trade_job_logic, daemon=True)
        t.start()

    def _trade_job_logic(self):
        # [NEW] 일시 정지 상태면 로직 건너뜀
        if self.state.is_paused or self.state.is_manual_stop:
            # print(f"\n🚫 [SKIP] 거래가 정지되었습니다.", end='')
            return

        current_price = fetch_current_price(cfg.SYMBOL)
        print(f"\n--- [Candle Close] {datetime.now().strftime('%H:%M:%S')} | Price: {current_price} ---")
        
        # [Multi-Timeframe] 현재 적용 중인 타임프레임으로 데이터 가져오기
        active_tf = self.state.get_active_timeframe()
        
        # Heavy Calculation (No Lock needed here, as we work on copies)
        df = fetch_raw_data(cfg.SYMBOL, active_tf, cfg.MAX_FETCH_LIMIT)
        if df is None: return

        if len(df) > self.state.config['max_bars_back']:
            df = df.tail(self.state.config['max_bars_back']).copy().reset_index(drop=True)
        
        # **Heavy Loop** (Indicators)
        df = add_indicators(df, self.state.config)
        df = generate_signals(df, self.state.config)
        
        sig = df['final_signal'].iloc[-1]
        price = df['close'].iloc[-1]
        atr_val = df['atr'].iloc[-1] if 'atr' in df.columns else 0.0 # [NEW]
        
        # [NEW] Hybrid Strategy Info
        st_trend = df['supertrend_trend'].iloc[-1] if 'supertrend_trend' in df.columns else 0
        extras = {'supertrend_trend': st_trend}
        
        # Critical Section: 매매 실행 및 상태 변경
        with self.lock:
            self.execute_trade_logic(sig, price, atr_val, extras)

    def execute_trade_logic(self, sig, price, atr=0.0, extras=None):
        # [Refactor] 모든 매매 로직 위임
        logs = self.state.process_tick(price, signal=sig, current_atr=atr, extras=extras)
        for log in logs:
            print(f" {log}")
        
    # ==================================================
    # [NEW] Manual Control Methods
    # ==================================================
    def kill_switch(self):
        with self.lock:
            self.state.is_manual_stop = True
            self.state.is_paused = True # 둘 다 True로 설정
            print(f"\n☠️ [KILL SWITCH] 봇을 강제 정지합니다! 모든 포지션을 청산합니다.")
            
            # 포지션 있으면 청산
            current_price = fetch_current_price(cfg.SYMBOL)
            if current_price:
                msg = self.state.manual_close_position(current_price, reason="Kill Switch")
                if msg: print(f"   -> {msg}")
            print("   -> 매매 기능 API 호출 차단됨.")

    def manual_close(self):
        with self.lock:
            print(f"\n👋 [Manual Close] 현재 포지션을 강제 청산합니다. (매매 로직은 유지)")
            current_price = fetch_current_price(config.SYMBOL)
            if current_price:
                msg = self.state.manual_close_position(current_price, reason="User Request")
                if msg: print(f"   -> {msg}")
                else: print("   -> 보유 중인 포지션이 없습니다.")

    def resume_trading(self):
        with self.lock:
            self.state.is_manual_stop = False
            self.state.is_paused = False
            print(f"\n▶️ [Resume] 거래를 재개합니다. (Kill Switch 해제)")