import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import core.trader as trader
from core.trade_state import TradeStateManager
from core.trader import TradingEngine

class _StubStrategy:
    """Minimal strategy stub: returns a prepared DataFrame from generate_signals."""

    def __init__(self, df_out):
        self.df_out = df_out
        self.calls = []

    def calculate_indicators(self, df):
        self.calls.append('calculate_indicators')
        return df

    def generate_signals(self, df):
        self.calls.append('generate_signals')
        return self.df_out


class TestFullFlow(unittest.TestCase):
    def setUp(self):
        # Setup mocks for external dependencies
        self.mock_logger = MagicMock()
        
        self.config = {
            'symbol': 'BTC/USDT',
            'timeframe': '5m',
            'start_balance': 1000.0,
            'fee_rate': 0.0, # Zero fee for easy calc
            'leverage': 1,
            'sl_ratio': 0.05,
            'max_bars_back': 50,
            # Indicators
            'rsi_length': 14,
            'wt_channel_len': 10,
            'wt_avg_len': 21,
            'cci_length': 20,
            'adx_length': 14,
            'ema_period': 10, 
            'neighbors': 5,
            'active_strategy': 'standard', # Uses JsonStrategy Logic
        }
        
    @patch('core.trader.fetch_raw_data')
    def test_trading_engine_analyze(self, mock_fetch):
        # Arrange
        engine = TradingEngine()
        
        # Mock Data (50 bars)
        dates = pd.date_range(start='2023-01-01', periods=50, freq='5min')
        df_mock = pd.DataFrame({
            'timestamp': dates,
            'open': np.linspace(100, 110, 50),
            'high': np.linspace(101, 111, 50),
            'low': np.linspace(99, 109, 50),
            'close': np.linspace(100, 110, 50), # Uptrend
            'volume': np.random.rand(50) * 1000
        })
        mock_fetch.return_value = df_mock
        
        # Act
        # The engine delegates indicators/signals to whatever strategy is passed
        # in, so a stub strategy is all that's needed to drive it.
        df_sig = df_mock.copy()
        df_sig['final_signal'] = 1 # Buy Signal
        df_sig['atr'] = 1.0

        sig, price, atr, extras = engine.analyze_market(
            self.config, '5m', _StubStrategy(df_sig)
        )

        # Assert
        self.assertEqual(sig, 1)
        self.assertEqual(price, 110.0)
        
    @patch('core.trader.fetch_raw_data')
    def test_full_loop_integration(self, mock_fetch):
        # Integration of Engine + State
        pass 
        # Actually simplest to just test state updates via engine outputs manually 
        # since we already tested Engine and State separately.
        # But let's verify parameters flow correctly.
        
        engine = TradingEngine()
        state = TradeStateManager(config=self.config, logger=self.mock_logger)
        
        # 1. Market Analysis
        dates = pd.date_range(start='2023-01-01', periods=50, freq='5min')
        df_mock = pd.DataFrame({
            'timestamp': dates,
            'open': [100]*50, 'high': [105]*50, 'low': [95]*50, 'close': [100]*50, 'volume': [1000]*50
        })
        mock_fetch.return_value = df_mock

        # Scenario: Buy Signal
        df_sig = df_mock.copy()
        df_sig['final_signal'] = 1
        df_sig['atr'] = 2.0

        # 2. Engine Run
        sig, price, atr, extras = engine.analyze_market(
            self.config, '5m', _StubStrategy(df_sig)
        )

        # 3. State Process
        state.process_tick(price, signal=sig, current_atr=atr, **extras)

        # Verify Position Opened
        self.assertEqual(state.position, 1)
        self.assertEqual(state.avg_entry, 100.0)
        self.assertEqual(state.entry_atr, 2.0)

if __name__ == '__main__':
    unittest.main()
