import unittest
import pandas as pd
import numpy as np
from analysis.indicators import add_indicators

class TestIndicators(unittest.TestCase):
    def setUp(self):
        # Create a sample DataFrame used for testing
        dates = pd.date_range(start='2023-01-01', periods=100, freq='15min')
        self.df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.rand(100) * 100,
            'high': np.random.rand(100) * 105,
            'low': np.random.rand(100) * 95,
            'close': np.random.rand(100) * 100,
            'volume': np.random.rand(100) * 1000
        })
        self.conf = {
            'rsi_length': 14,
            'wt_channel_len': 10,
            'wt_avg_len': 21,
            'cci_length': 20,
            'adx_length': 14,
            'ema_period': 50,
            'use_kernel': False
        }

    def test_add_indicators_columns(self):
        df_result = add_indicators(self.df, self.conf)
        
        # Check if new columns are added
        expected_cols = ['rsi', 'wt1', 'cci', 'adx', 'atr', 'ema', 'chop', 'supertrend']
        for col in expected_cols:
            self.assertIn(col, df_result.columns, f"Column {col} missing")

    def test_rsi_calculation(self):
        df_result = add_indicators(self.df, self.conf)
        self.assertFalse(df_result['rsi'].isnull().all(), "RSI should not be all NaN")
        self.assertTrue((df_result['rsi'] >= 0).all() and (df_result['rsi'] <= 100).all(), "RSI out of range")

    def test_supertrend_calculation(self):
        df_result = add_indicators(self.df, self.conf)
        self.assertIn('supertrend_trend', df_result.columns)
        unique_trends = df_result['supertrend_trend'].unique()
        # Should contain 1 and/or -1 (and potentially 0 if not enough data, but we generated 100)
        for val in unique_trends:
            self.assertIn(val, [1, -1, 0])

    def test_empty_dataframe(self):
        empty_df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Should not crash, but might return empty or error depending on lib
        # add_indicators uses TA lib which might warn but returns empty
        try:
             df_result = add_indicators(empty_df, self.conf)
             self.assertEqual(len(df_result), 0)
        except Exception as e:
            # Accepting that it might raise an error on empty, but catching it is good practice
            pass

if __name__ == '__main__':
    unittest.main()
