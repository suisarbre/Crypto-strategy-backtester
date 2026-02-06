# utils.py
import socket
import warnings
import requests.packages.urllib3.util.connection as urllib3_cn

def apply_patches():
    # IPv4 강제 설정 및 경고 무시
    def allowed_gai_family():
        return socket.AF_INET
    urllib3_cn.allowed_gai_family = allowed_gai_family
    warnings.filterwarnings('ignore')

from datetime import datetime
import time
import math

def wait_until_next_candle(interval_minutes):
    """
    다음 캔들 마감 시간(정각 기준 5분 단위 등)까지 대기합니다.
    """
    now = datetime.now()
    # 현재 시간의 '분'을 interval로 나눈 나머지
    # 예: interval=5, 분=12 -> 나머지 2 -> 3분 더 기다려야 함 (15분에 실행)
    minutes_to_next = interval_minutes - (now.minute % interval_minutes)
    
    # 초 단위 계산: (남은 분 * 60) - 현재 초
    seconds_to_wait = (minutes_to_next * 60) - now.second
    # 마이크로초 보정 (완벽한 정각보다 약간 늦게 실행되게 -0.1초 할 수도 있지만, 넉넉히 기다림)
    
    if seconds_to_wait <= 0:
        seconds_to_wait += interval_minutes * 60
        
    target_time = time.time() + seconds_to_wait
    target_dt = datetime.fromtimestamp(target_time)
    
    print(f"\n⏳ [Sync] 다음 캔들 마감({target_dt.strftime('%H:%M:00')})까지 {int(seconds_to_wait)}초 대기합니다...")
    
    # 1초씩 카운트다운하며 대기 (모니터링 차단 방지용은 아니지만, 시작 전이므로 단순 sleep)
    # 길면 5분일 수 있으니 그냥 sleep
    time.sleep(seconds_to_wait + 1) # 1초 여유
    print(f"✅ 동기화 완료! 스케줄러를 시작합니다.")

def get_next_candle_time(interval_minutes):
    """
    다음 캔들 마감 시각(Timestamp)을 계산하여 반환합니다.
    (예: 현재 12:03, interval 5 -> 12:05:00의 timestamp 반환)
    """
    now = datetime.now()
    minutes_to_next = interval_minutes - (now.minute % interval_minutes)
    seconds_to_wait = (minutes_to_next * 60) - now.second
    # 마이크로초 절삭을 위해 정수형으로 처리하거나 현재 시간 기준 정밀 계산
    
    if seconds_to_wait <= 0:
        seconds_to_wait += interval_minutes * 60
        
    target_time = time.time() + seconds_to_wait
    # 정확히 00초로 맞추기 위해 보정 (선택 사항이나 깔끔함을 위해)
    # target_time을 기준으로 datetime 변환 후 초/마이크로초 0으로 리셋하는게 더 정확할 수 있음
    
    
    # 더 안전한 방법: 미래의 가장 가까운 (시*60 + 분) % interval == 0 인 시점 찾기
    return target_time

def parse_timeframe_to_minutes(tf_str):
    """
    TIMEFRAME 문자열(예: '5m', '1h', '4h')을 분 단위 정수로 변환합니다.
    """
    if not tf_str: return 5
    
    unit = tf_str[-1].lower()
    try:
        val = int(tf_str[:-1])
    except ValueError:
        return 5 # 기본값
        
    if unit == 'm':
        return val
    elif unit == 'h':
        return val * 60
    elif unit == 'd':
        return val * 1440
    else:
        return 5 # 알 수 없는 단위면 기본 5분

import threading
import sys

def start_command_listener(bot):
    """
    별도 스레드에서 사용자 입력을 대기하고 봇을 제어합니다.
    """
    def listen():
        print("⌨️ [Command] 명령어 입력 가능 (k: 킬스위치, r: 재개, c: 청산만, enter: 현황)")
        while True:
            try:
                # Windows Console에서 한글 입력 시 깨질 수 있으므로 영문 권장
                # input()은 블로킹 함수이므로 별도 스레드 필수
                cmd = input().strip().lower()
                
                if cmd in ['k', 'kill']:
                    bot.kill_switch()
                elif cmd in ['r', 'resume', 'start']:
                    bot.resume_trading()
                elif cmd in ['c', 'close']:
                    bot.manual_close()
                elif cmd == '':
                    pass # 엔터 키는 그냥 무시 (로그 줄바꿈 용도)
                else:
                    print(f"⚠️ 알 수 없는 명령어: {cmd}")
            except EOFError:
                break
            except Exception as e:
                print(f"Error reading input: {e}")
                
    t = threading.Thread(target=listen, daemon=True)
    t.start()