import unittest
import numpy as np
import pandas as pd
import json
import os
try:
    import cpp_engine
except ImportError:
    cpp_engine = None

class TestOptimizerDynamic(unittest.TestCase):
    def setUp(self):
        # Create dummy market data
        self.n = 500
        self.open = np.linspace(100, 200, self.n)
        self.high = self.open + 5
        self.low = self.open - 5
        self.close = self.open + 2 # Minor uptrend
        
        # Mock Strategy JSON
        self.strategy_config = {
            "name": "TestStrategy",
            "definitions": {
                "indicators": [
                    {
                        "name": "my_rsi",
                        "type": "rsi",
                        "source": "close",
                        "length": "rsi_len" # Dynamic
                    },
                    {
                        "name": "my_static_ema",
                        "type": "ema",
                        "source": "close",
                        "length": 50 # Static
                    }
                ]
            },
            "entry_rules": {
                "long": [{
                    "type": "compare",
                    "left": "my_rsi",
                    "op": "<",
                    "right": 30
                }]
            },
            "exit_rules": {
                "long": [{
                    "type": "compare",
                    "left": "my_rsi",
                    "op": ">",
                    "right": 70
                }]
            }
        }
        self.strategy_json = json.dumps(self.strategy_config)

    def test_generic_interface_structure(self):
        """Verify we can call optimize_generic with correct types"""
        if not cpp_engine:
            print("Skipping C++ test (module not found)")
            return

        ind_names = ["rsi_len"]
        ind_values = [[10, 14, 20]]
        
        filt_names = ["leverage"]
        filt_values = [[1]]
        
        # Should not crash
        try:
            results = cpp_engine.optimize_generic(
                self.open, self.high, self.low, self.close,
                ind_names, ind_values,
                filt_names, filt_values,
                self.strategy_json,
                1, 100, 0.5, 10000.0,
                0.001, 0.05, 0.02, # fee, tp, sl
                8, 8.0, 3 # Kernel params (unused in this strategy but required signature)
            )
            print(f"Generic Optimizer returned {len(results)} results")
            self.assertTrue(isinstance(results, list))
        except Exception as e:
            self.fail(f"optimize_generic raised exception: {e}")

if __name__ == '__main__':
    unittest.main()
