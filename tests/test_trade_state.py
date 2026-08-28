import unittest
from unittest.mock import MagicMock
from core.trade_state import TradeStateManager

class TestTradeStateManager(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        self.config = {
            'start_balance': 1000.0,
            'fee_rate': 0.001,
            'leverage': 1,
            'sl_ratio': 0.05
        }
        self.state = TradeStateManager(config=self.config, logger=self.mock_logger)
        # Override balance for deterministic testing
        self.state.balance = 1000.0

    def test_open_position(self):
        # Act
        self.state.open_position(1, 100.0, 1.0) # Long @ 100, ATR 1.0
        
        # Assert
        self.assertEqual(self.state.position, 1)
        self.assertEqual(self.state.avg_entry, 100.0)
        self.assertEqual(self.state.entry_atr, 1.0)
        self.mock_logger.log_trade.assert_called_with(
            event="ENTRY", symbol='UNKNOWN', side="LONG", price=100.0, pnl=0, balance=1000.0, leverage=1, config=self.config
        )

    def test_close_position_profit(self):
        # Arrange
        self.state.open_position(1, 100.0)
        self.state.balance = 1000.0
        
        # Act: Close at 110 (10% profit)
        lev_pnl = 0.10
        msg = self.state.close_position(110.0, "TestExit", lev_pnl)
        
        # Assert
        expected_balance = 1000.0 * (1 + 0.10 - 0.001) # 1000 * 1.099 = 1099.0
        self.assertAlmostEqual(self.state.balance, expected_balance)
        self.assertEqual(self.state.position, 0)
        self.mock_logger.log_trade.assert_called()
        self.assertIn("TestExit", msg)

    def test_process_tick_sl(self):
        # Arrange
        # sl_ratio must stay inside DAILY_LOSS_LIMIT (5%), otherwise the daily
        # guard preempts the stop-loss and closes with its own reason (ADR-004).
        self.state.config['sl_ratio'] = 0.03 # 3% SL
        self.state.open_position(1, 100.0)

        # Act: Price drops to 96 (-4%)
        logs = self.state.process_tick(96.0)

        # Assert
        self.assertEqual(self.state.position, 0) # Should be closed due to SL
        self.assertIn("stop_loss", logs[0])
        self.assertFalse(self.state.is_paused) # a normal stop does not pause the day

    def test_daily_loss_preempts_a_wider_stop_loss(self):
        """
        If sl_ratio exceeds DAILY_LOSS_LIMIT the hard stop is unreachable — the
        daily guard fires first, closes the position, and pauses for the day.
        Pins the precedence so the config invariant is visible.
        """
        # Arrange
        self.state.config['sl_ratio'] = 0.10 # 10% SL, wider than the 5% daily limit
        self.state.open_position(1, 100.0)

        # Act: Price drops to 89 (-11%)
        logs = self.state.process_tick(89.0)

        # Assert
        self.assertEqual(self.state.position, 0)
        self.assertIn("DailyLossLimit", logs[0])
        self.assertTrue(self.state.is_paused)

    def test_process_tick_delegates_to_strategy(self):
        # Arrange
        self.state.logic = MagicMock()
        self.state.logic.process_signal.return_value = ["Strategy Log"]
        self.state.open_position(1, 100.0)
        
        # Act
        logs = self.state.process_tick(100.0, signal=1, current_atr=1.0)
        
        # Assert
        self.state.logic.process_signal.assert_called_once()
        self.assertIn("Strategy Log", logs)

if __name__ == '__main__':
    unittest.main()
