
import unittest
import pandas as pd
import numpy as np
import json
from analysis.signal_evaluator import SignalEvaluator

class TestSignalEvaluator(unittest.TestCase):
    def setUp(self):
        self.strategy = {
            "strategy_name": "TestStrat",
            "entry_rules": {
                "long": [
                    {"op": "and", "rules": [
                        {"type": "compare", "left": "rsi", "op": "<", "right": 30},
                        {"type": "condition", "if": "use_filter", "then": [
                            {"type": "compare", "left": "close", "op": ">", "right": "ema"}
                        ]}
                    ]}
                ],
                "short": [
                    {"type": "compare", "left": "rsi", "op": ">", "right": 70}
                ]
            }
        }
        self.evaluator = SignalEvaluator(json.dumps(self.strategy))
        
        # Create Dummy Data
        self.df = pd.DataFrame({
            "close": [100, 105, 110, 95, 90],
            "ema":   [101, 101, 101, 101, 101],
            "rsi":   [25,  80,  20,  25,  80]
        })
        
    def test_evaluate_long_no_filter(self):
        params = {"use_filter": 0.0}
        signals = self.evaluator.evaluate(self.df, params)
        # Long: RSI < 30. Indices: 0 (25), 2 (20), 3 (25)
        # Short: RSI > 70. Indices: 1 (80), 4 (80)
        
        # Expected: 1, -1, 1, 1, -1
        expected = np.array([1, -1, 1, 1, -1])
        np.testing.assert_array_equal(signals, expected)
        print("Test Long No Filter: PASS")

    def test_evaluate_long_with_filter(self):
        params = {"use_filter": 1.0}
        signals = self.evaluator.evaluate(self.df, params)
        # Long: RSI < 30 AND Close > EMA.
        # Index 0: 25 < 30 (OK), 100 > 101 (FAIL) -> 0
        # Index 2: 20 < 30 (OK), 110 > 101 (PASS) -> 1
        # Index 3: 25 < 30 (OK), 95 > 101 (FAIL) -> 0
        
        # Short: RSI > 70 (No filter in rule).
        # Index 1: 80 > 70 -> -1
        # Index 4: 80 > 70 -> -1
        
        # Expected: 0, -1, 1, 0, -1
        expected = np.array([0, -1, 1, 0, -1])
        np.testing.assert_array_equal(signals, expected)
        print("Test Long With Filter: PASS")

if __name__ == '__main__':
    unittest.main()
