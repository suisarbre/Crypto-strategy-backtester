import unittest
import pandas as pd
import numpy as np
from strategies.lorentzian import LorentzianStrategy
import config as cfg

class TestLorentzianStrategy(unittest.TestCase):
    def setUp(self):
        # Create a dummy dataframe
        dates = pd.date_range(start='2023-01-01', periods=100, freq='h')
        self.df = pd.DataFrame({
            'open': np.random.uniform(100, 110, 100),
            'high': np.random.uniform(110, 120, 100),
            'low': np.random.uniform(90, 100, 100),
            'close': np.random.uniform(100, 110, 100),
            'volume': np.random.uniform(1000, 5000, 100)
        }, index=dates)
        
        # Default Config
        self.config = {
            'rsi_length': 14,
            'wt_channel_len': 10,
            'wt_avg_len': 21,
            'cci_length': 20,
            'adx_length': 14,
            'neighbors': 8,
            'use_kernel': True
        }
        self.strategy = LorentzianStrategy(self.config)

    def test_calculate_indicators(self):
        df_out = self.strategy.calculate_indicators(self.df)
        
        # Check if columns exist
        expected_cols = ['rsi', 'wt1', 'cci', 'adx', 'atr', 'ema', 'kernel']
        for col in expected_cols:
            self.assertIn(col, df_out.columns, f"Column {col} missing from indicators")
            
        # Check values are not all NaN (after warm-up period)
        self.assertFalse(df_out['rsi'].iloc[-1] == 0, "RSI should not be 0 unless initialized that way")
        self.assertFalse(df_out['kernel'].isnull().all(), "Kernel should contain values")

    def test_generate_signals(self):
        # First calculate indicators
        df_ind = self.strategy.calculate_indicators(self.df)
        
        # Then generate signals
        df_sig = self.strategy.generate_signals(df_ind)
        
        # Check for signal columns
        self.assertIn('pred_signal', df_sig.columns)
        self.assertIn('final_signal', df_sig.columns)
        
        # Check specific values
        unique_signals = df_sig['final_signal'].unique()
        for sig in unique_signals:
            self.assertIn(sig, [0, 1, -1], f"Invalid signal value: {sig}")

    def test_parameter_ranges(self):
        ranges = self.strategy.get_parameter_ranges()
        self.assertIsInstance(ranges, dict)
        self.assertIn('rsi_length', ranges)
        self.assertIn('neighbors', ranges)

if __name__ == '__main__':
    unittest.main()
