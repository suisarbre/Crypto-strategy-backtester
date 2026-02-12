# main.py
import time
import schedule
import sys
from datetime import datetime
from core.trader import PaperTrader
import utils
import config as cfg


from gui.dashboard import dashboard # Import Dashboard Instance
from nicegui import ui

def main():
    # 1. 초기 설정
    utils.apply_patches()
    
    # 2. 트레이더 봇 생성
    bot = PaperTrader()
    
    # 3. 대시보드 연결 (모든 제어권 이양)
    dashboard.set_bot(bot)
    
    print(f"=== Lorentzian Bot WebUI Started ===")
    print(f"👉 Open Browser at http://localhost:8080")
    
    # 4. 스케줄 등록 (대시보드가 run_pending 호출함)
    schedule.every(cfg.OPTIMIZE_INTERVAL_MINUTES).minutes.do(bot.run_optimization_thread)
    # schedule.every(1).seconds.do(bot.monitor_position) # 콘솔 모니터링은 필요 시 주석 해제
    
    # [Start]
    # utils.start_command_listener(bot) # 웹 제어로 대체하므로 콘솔 리스너는 선택 사항
    
    # Run UI
    ui.run(title='Lorentzian Bot', dark=True, port=8080, reload=False) # reload=False for stability

if __name__ in {"__main__", "__mp_main__"}:
    main()