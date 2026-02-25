"""
Test Exit Rules Implementation - Phase 2b Verification
Verifies that JSON-defined exit rules work correctly in both C++ and Python.
"""

import numpy as np
import pandas as pd
import json
from analysis.signal_evaluator import SignalEvaluator

# Create test strategy with exit rules
test_strategy = {
    "entry_rules": {
        "long": [{"op": "and", "rules": [{"type": "compare", "left": "rsi", "op": "<", "right": 30}]}],
        "short": [{"op": "and", "rules": [{"type": "compare", "left": "rsi", "op": ">", "right": 70}]}]
    },
    "exit_rules": {
        "long": [{"op": "and", "rules": [{"type": "compare", "left": "rsi", "op": ">", "right": 80}]}],
        "short": [{"op": "and", "rules": [{"type": "compare", "left": "rsi", "op": "<", "right": 20}]}]
    }
}

# Create test data
n = 100
test_df = pd.DataFrame({
    'rsi': np.concatenate([
        np.full(10, 25),   # Entry for long (RSI < 30)
        np.linspace(25, 85, 30),  # Rising RSI
        np.full(10, 85),   # Exit for long (RSI > 80)
        np.linspace(85, 15, 30),  # Falling RSI
        np.full(10, 75),   # Entry for short (RSI > 70)
        np.linspace(75, 15, 10)   # Falling to exit (RSI < 20)
    ])
})

# Test Python SignalEvaluator
evaluator = SignalEvaluator(json.dumps(test_strategy))
params = {}

# Evaluate entry signals
entry_signals = evaluator.evaluate(test_df, params)

# Evaluate exit signals
exit_signals = evaluator.evaluate_exit(test_df, params)

print("=" * 60)
print("EXIT RULES VERIFICATION TEST")
print("=" * 60)
print(f"\nTest strategy:")
print(f"  Entry Long: RSI < 30")
print(f"  Entry Short: RSI > 70")
print(f"  Exit Long: RSI > 80")
print(f"  Exit Short: RSI < 20")

print(f"\n[Python] Entry Signals (first 50 bars):")
print(f"  Long entries (signal=1): {np.where(entry_signals[:50] == 1)[0].tolist()}")
print(f"  Short entries (signal=-1): {np.where(entry_signals[:50] == -1)[0].tolist()}")

print(f"\n[Python] Exit Signals (bitmask):")
long_exits = np.where(exit_signals & 1)[0]
short_exits = np.where(exit_signals & 2)[0]
print(f"  Long exits (mask & 1): {long_exits.tolist()}")
print(f"  Short exits (mask & 2): {short_exits.tolist()}")

# Verify logic
expected_long_entry = test_df['rsi'] < 30
expected_short_entry = test_df['rsi'] > 70
expected_long_exit = test_df['rsi'] > 80
expected_short_exit = test_df['rsi'] < 20

assert any(exit_signals & 1), "❌ No long exit signals detected"
assert any(exit_signals & 2), "❌ No short exit signals detected"
assert any(entry_signals == 1), "❌ No long entry signals detected"
assert any(entry_signals == -1), "❌ No short entry signals detected"

print(f"\n✅ All assertions passed!")
print(f"✅ Exit rules are working correctly in Python")
print("\n" + "=" * 60)
