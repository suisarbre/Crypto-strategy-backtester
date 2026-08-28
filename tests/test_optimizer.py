import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import core.optimizer as optimizer

class TestOptimizer(unittest.TestCase):
    def test_transform_ranges(self):
        ranges = {
            'rsi': [14, 21],
            'adx_threshold': [20, 25],
            'use_ema_filter': [0, 1]
        }
        
        ind_names, ind_vals, filt_names, filt_vals = optimizer.transform_ranges_to_generic_format(ranges)
        
        self.assertIn('rsi_length', ind_names)
        self.assertIn([14.0, 21.0], ind_vals)
        self.assertIn('adx_threshold', filt_names)
        self.assertIn('use_ema_filter', filt_names)

    @patch('core.optimizer.fetch_raw_data')
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='{}')
    def test_execute_optimization_logic_cpp(self, mock_open, mock_exists, mock_fetch):
        # Arrange
        # Mock Data
        dates = pd.date_range(start='2023-01-01', periods=1000, freq='15min')
        df_mock = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.rand(1000) * 100,
            'high': np.random.rand(1000) * 105,
            'low': np.random.rand(1000) * 95,
            'close': np.random.rand(1000) * 100,
            'volume': np.random.rand(1000) * 1000
        })
        mock_fetch.return_value = df_mock
        
        # Mock C++ Result
        mock_res = [{
            'best_score': 100.0,
            'balance': 150.0,
            'wins': 10,
            'trades': 15,
            'mdd': 0.1,
            'best_params': {'rsi_length': 14, 'neighbors': 5, 'adx_threshold': 25} # Ensure params exist for plateau check
        }]
        
        mock_cpp = MagicMock()
        mock_cpp.optimize_generic.return_value = mock_res
        
        # Config
        current_config = {
             'symbol': 'BTC/USDT',
             'timeframe': '5m',
             'optimizer_min_trades': 5,
             'optimizer_max_mdd': 0.3,
             # Default params needed for range generation
             'rsi_length': 14,
             'wt_channel_len': 10,
             'wt_avg_len': 21,
             'cci_length': 20,
             'adx_length': 14,
             'adx_threshold': 25,
             'neighbors': 8,
             'leverage': 1,
             'use_ema_filter': 1,
             'use_adx_filter': 1,
             'ema_period': 200,
             'sl_multiplier': 3.0
        }

        # Act
        # USE_PSO must be off: this test exercises the grid path via
        # optimize_generic. With PSO on, the unconfigured mock's optimize_pso
        # returns a truthy MagicMock, the grid fallback never fires, and the
        # optimizer reports no valid results.
        with patch.dict('sys.modules', {'cpp_engine': mock_cpp}):
            with patch('config.AVAILABLE_TIMEFRAMES', ['5m']), \
                 patch('config.AVAILABLE_STRATEGIES', ['standard']), \
                 patch('config.USE_PSO', False):
                 
                best_params, wins, trades, mdd, bal, score = optimizer.execute_optimization_logic(current_config)
        
        # Assert
        self.assertEqual(score, 100.0)
        self.assertEqual(bal, 150.0)
        self.assertEqual(best_params['rsi_length'], 14)
        mock_cpp.optimize_generic.assert_called()

if __name__ == '__main__':
    unittest.main()
