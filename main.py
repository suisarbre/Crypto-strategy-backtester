# main.py
import time
import schedule
import sys
from datetime import datetime
from core.trader import PaperTrader
import utils
import config as cfg


def main():
    # 1. 초기 설정
    utils.apply_patches()
    
    # 2. 트레이더 봇 생성
    bot = PaperTrader()
    
    print(f"=== Lorentzian Bot Started ===")
    
    # 3. 초기 최적화 실행 (동기식으로 1회 실행 권장)
    print("초기 최적화 진행 중...")
    bot._optimize_worker() 
    
    # 4. 스케줄 등록
    # TIMEFRAME 파싱 (예: '5m' -> 5, '1h' -> 60)
    interval_minutes = utils.parse_timeframe_to_minutes(cfg.TIMEFRAME)
    
    print(f"⏰ 스케줄 설정: {cfg.TIMEFRAME} ({interval_minutes}분 단위 실행)")
    
    # [Sync] 다음 캔들 마감 시점 계산
    next_candle_time = utils.get_next_candle_time(interval_minutes)
    next_dt = datetime.fromtimestamp(next_candle_time)
    print(f"⏳ [Sync] 첫 실행 예정 시각: {next_dt.strftime('%H:%M:%S')}")
    
    schedule.every(cfg.OPTIMIZE_INTERVAL_MINUTES).minutes.do(bot.run_optimization_thread)
    # schedule.every(interval_minutes).minutes.do(bot.trade_job) # [Del] 스케줄러 대신 수동 루프 사용
    schedule.every(1).seconds.do(bot.monitor_position) # 실시간 모니터링
    
    # [NEW] 커맨드 리스너 스레드 시작
    utils.start_command_listener(bot)
    
    # 5. 실행 루프 (Drift-Free)
    current_interval_minutes = interval_minutes # 초기값
    interval_seconds = current_interval_minutes * 60
    
    while True:
        now = time.time()
        
        # [Multi-Timeframe] 능동적 타임프레임 감지
        # 봇의 상태(포지션 보유 여부 등)에 따라 타임프레임이 달라질 수 있음
        active_tf = bot.state.get_active_timeframe()
        active_minutes = utils.parse_timeframe_to_minutes(active_tf)
        
        # 타임프레임 변경 감지 시 스케줄 재설정
        if active_minutes != current_interval_minutes:
            print(f"\n🔄 [System] 타임프레임 변경 감지: {current_interval_minutes}m -> {active_minutes}m")
            current_interval_minutes = active_minutes
            interval_seconds = current_interval_minutes * 60
            
            # 다음 캔들 마감 시각 재계산 (현재 시각 기준으로 가장 가까운 미래의 마감)
            next_candle_time = utils.get_next_candle_time(current_interval_minutes)
            next_dt = datetime.fromtimestamp(next_candle_time)
            print(f"⏳ [Sync] 재동기화 완료! 다음 실행: {next_dt.strftime('%H:%M:%S')}")

        # 캔들 마감 체크
        if now >= next_candle_time:
            bot.trade_job()
            # 다음 목표 시각 갱신
            next_candle_time += interval_seconds 
            
            # 로그 출력 (선택)
            # tgt = datetime.fromtimestamp(next_candle_time).strftime('%H:%M:%S')
            # print(f"  [Next] {tgt}")

        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()