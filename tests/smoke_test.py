import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trader import TradingEngine
import strategies
import config as cfg

def run_smoke_test():
    print("[INFO] Starting Smoke Test...")
    
    # 1. Initialize Engine
    try:
        engine = TradingEngine()
        print("[OK] TradingEngine Initialized")
    except Exception as e:
        print(f"[FAIL] Failed to init engine: {e}")
        return

    # 2. Resolve the strategy the engine will run with.
    # The engine holds no strategy of its own — it is passed in per call.
    strategy = strategies.get_strategy(cfg.ACTIVE_STRATEGY)
    print(f"[INFO] Active Strategy: {strategy.__class__.__name__}")

    # 3. Analyze Market (Dry Run)
    print("[INFO] Running analyze_market()...")
    try:
        # Mock config
        conf = cfg.CURRENT_CONFIG
        timeframe = '15m' # Use a standard timeframe

        # We need to make sure we can fetch data.
        # If fetch_raw_data fails (network), we might want to mock it,
        # but for a smoke test, real connectivity check is also good.
        result = engine.analyze_market(conf, timeframe, strategy)
        if result is None:
             print("[FAIL] analyze_market returned None (Data fetch failed?)")
             return
             
        sig, price, atr, extras = result
        
        print(f"[OK] Analysis Complete.")
        print(f"   Signal: {sig}")
        print(f"   Price: {price}")
        print(f"   ATR: {atr}")
        print(f"   Extras: {list(extras.keys())}")
        
    except Exception as e:
        print(f"[FAIL] Analysis Failed: {e}")
        return

    print("[SUCCESS] Smoke Test Passed!")

if __name__ == "__main__":
    run_smoke_test()
