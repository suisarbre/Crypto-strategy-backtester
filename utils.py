# utils.py
import socket
import warnings
import requests.packages.urllib3.util.connection as urllib3_cn

def apply_patches():
    """Force IPv4 connections and suppress warnings."""
    def allowed_gai_family():
        return socket.AF_INET
    urllib3_cn.allowed_gai_family = allowed_gai_family
    warnings.filterwarnings('ignore')

from datetime import datetime
import time
import math

def wait_until_next_candle(interval_minutes):
    """
    Sleep until the next candle close (aligned to clock intervals).
    Example: interval=5, current time 12:03 → sleeps until 12:05:00.
    """
    now = datetime.now()
    minutes_to_next = interval_minutes - (now.minute % interval_minutes)
    seconds_to_wait = (minutes_to_next * 60) - now.second
    
    if seconds_to_wait <= 0:
        seconds_to_wait += interval_minutes * 60
        
    target_time = time.time() + seconds_to_wait
    target_dt = datetime.fromtimestamp(target_time)
    
    print(f"\n⏳ [Sync] Waiting {int(seconds_to_wait)}s until next candle close ({target_dt.strftime('%H:%M:00')})…")
    
    time.sleep(seconds_to_wait + 1)  # +1s buffer
    print(f"✅ Sync complete — starting scheduler.")

def get_next_candle_time(interval_minutes):
    """
    Calculate the timestamp of the next candle close.
    Example: current 12:03, interval 5 → returns timestamp for 12:05:00.
    """
    now = datetime.now()
    minutes_to_next = interval_minutes - (now.minute % interval_minutes)
    seconds_to_wait = (minutes_to_next * 60) - now.second
    
    if seconds_to_wait <= 0:
        seconds_to_wait += interval_minutes * 60
        
    target_time = time.time() + seconds_to_wait
    return target_time

def parse_timeframe_to_minutes(tf_str):
    """Convert a timeframe string (e.g. '5m', '1h', '4h') to integer minutes."""
    if not tf_str: return 5
    
    unit = tf_str[-1].lower()
    try:
        val = int(tf_str[:-1])
    except ValueError:
        return 5
        
    if unit == 'm':
        return val
    elif unit == 'h':
        return val * 60
    elif unit == 'd':
        return val * 1440
    else:
        return 5

import threading
import sys

def start_command_listener(bot):
    """
    Listen for keyboard commands in a daemon thread.
    Commands: k=kill, r=resume, c=close position.
    """
    def listen():
        print("⌨️ [Command] Available: k=kill, r=resume, c=close, Enter=refresh")
        while True:
            try:
                cmd = input().strip().lower()
                
                if cmd in ['k', 'kill']:
                    bot.kill_switch()
                elif cmd in ['r', 'resume', 'start']:
                    bot.resume_trading()
                elif cmd in ['c', 'close']:
                    bot.manual_close()
                elif cmd == '':
                    pass
                else:
                    print(f"⚠️ Unknown command: {cmd}")
            except EOFError:
                break
            except Exception as e:
                print(f"Error reading input: {e}")
                
    t = threading.Thread(target=listen, daemon=True)
    t.start()