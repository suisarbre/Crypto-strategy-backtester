import sys
import os
import datetime # [FIX] Import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trade_state import TradeStateManager
import config.trading as cfg

def test_daily_loss_limit():
    print("\n[Test 1] Daily Loss Limit")
    state = TradeStateManager()
    # [FIX] Set date to prevent auto-reset logic
    state.last_trade_date = datetime.date.today()
    state.daily_start_balance = 1000.0
    state.balance = 1000.0
    cfg.DAILY_LOSS_LIMIT = 0.05 # 5%

    # 1. Simluate Loss
    # Lose 60 (6%)
    state.balance = 940.0
    
    # Check
    state._check_daily_loss(current_price=100)
    
    if state.is_paused:
        print("[PASS] Daily Loss Limit Reached. Trading Paused.")
    else:
        print(f"[FAIL] Trading NOT paused. (Start: {state.daily_start_balance}, Curr: {state.balance})")

def test_trailing_stop_centralized():
    print("\n[Test 2] Centralized Trailing Stop")
    state = TradeStateManager()
    state.balance = 1000.0
    cfg.USE_TRAILING_STOP = True
    cfg.TS_ACTIVATION = 0.02 # 2% profit activates
    cfg.TS_CALLBACK = 0.01   # 1% trail
    
    # Open Long @ 100
    state.open_position(1, price=100.0)
    
    # 1. Move Price to 101 (1%) -> No Activation
    state._check_risk_management(price=101.0, atr=0)
    if state.trailing_stop_price == 0:
        print("[PASS] Step 1: TS Not activated at 1% profit.")
    else:
        print("[FAIL] Step 1: TS Activated too early.")
        
    # 2. Move Price to 103 (3%) -> Activation (TS should be 103 * 0.99 = 101.97)
    state._check_risk_management(price=103.0, atr=0)
    if state.trailing_stop_price > 0:
        print(f"[PASS] Step 2: TS Activated at 3% profit. TS Price: {state.trailing_stop_price:.2f}")
    else:
        print("[FAIL] Step 2: TS Failed to activate.")
        
    # 3. Drop Price to 101 (Below 101.97) -> Execute Exit
    log = state._check_risk_management(price=101.0, atr=0)
    if log and "TrailingStop" in log:
        print("[PASS] Step 3: Exit Triggered on Drop.")
    else:
        print(f"[FAIL] Step 3: Exit Failed. Log content hidden.")

def test_breakeven_centralized():
    print("\n[Test 3] Centralized Breakeven")
    state = TradeStateManager()
    state.balance = 1000.0
    cfg.USE_BREAKEVEN = True
    cfg.USE_TRAILING_STOP = True # BE interacts with TS price
    cfg.BE_TRIGGER = 0.015 # 1.5%
    cfg.BE_OFFSET = 0.002  # 0.2%
    
    # Open Long @ 100
    state.open_position(1, price=100.0)
    
    # 1. Move to 101.6 (1.6%) -> Trigger BE
    # BE Price = 100 * 1.002 = 100.2
    state._check_risk_management(price=101.6, atr=0)
    
    if state.trailing_stop_price >= 100.2:
        print(f"[PASS] TS Price moved to Breakeven level ({state.trailing_stop_price:.2f} >= 100.2)")
    else:
        print(f"[FAIL] BE not applied. TS Price: {state.trailing_stop_price}")

if __name__ == "__main__":
    test_daily_loss_limit()
    test_trailing_stop_centralized()
    test_breakeven_centralized()
