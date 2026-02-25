import unittest
from unittest.mock import MagicMock
import pandas as pd
import numpy as np
from strategies.json_strategy import JsonStrategyLogic

class TestJsonStrategyLogic(unittest.TestCase):
    def setUp(self):
        self.logic = JsonStrategyLogic()
        self.mock_state = MagicMock()
        self.mock_state.config = {
            'use_trailing_stop': True,
            'use_partial_exit': True,
            'sl_multiplier': 3.0,
            'breakeven_trigger_atr': 0.0
        }
        self.mock_state.position = 0
        self.mock_state.balance = 1000.0
        self.mock_state.avg_entry = 0.0
        self.mock_state.entry_leverage = 1.0
        self.mock_state.partial_done = False
        self.mock_state.trailing_stop_price = 0.0
        
        # Mock methods
        self.mock_state.open_position = MagicMock()
        self.mock_state.close_position = MagicMock(return_value="Closed Position")

    def test_entry_long(self):
        # Arrrange
        price = 100.0
        signal = 1
        atr = 1.0
        
        # Act
        logs = self.logic.process_signal(self.mock_state, price, signal, atr, {})
        
        # Assert
        self.mock_state.open_position.assert_called_with(1, price, atr)
        self.assertIn("🔵 [LONG] Entry", logs[0])

    def test_entry_short(self):
        # Arrange
        price = 100.0
        signal = -1
        atr = 1.0
        
        # Act
        logs = self.logic.process_signal(self.mock_state, price, signal, atr, {})
        
        # Assert
        self.mock_state.open_position.assert_called_with(-1, price, atr)
        self.assertIn("🔴 [SHORT] Entry", logs[0])

    def test_exit_signal_long(self):
        # Arrange
        self.mock_state.position = 1
        self.mock_state.avg_entry = 90.0
        price = 100.0
        signal = 0
        atr = 1.0
        extras = {'exit_signal': 1} # 1 = Long Exit
        
        # Act
        logs = self.logic.process_signal(self.mock_state, price, signal, atr, extras)
        
        # Assert
        self.mock_state.close_position.assert_called_with(price, "StrategyExit", ((100-90)/90))
        self.assertIn("Closed Position", logs)

    def test_trailing_stop_activation_long(self):
        # Arrange
        self.mock_state.position = 1
        self.mock_state.avg_entry = 100.0
        self.mock_state.trailing_stop_price = 95.0
        price = 110.0
        atr = 2.0
        # New TS should be 110 - (2.0 * 3.0) = 104.0
        
        # Act
        self.logic.process_signal(self.mock_state, price, 0, atr, {})
        
        # Assert
        self.assertEqual(self.mock_state.trailing_stop_price, 104.0)

    def test_trailing_stop_hit_long(self):
        # Arrange
        self.mock_state.position = 1
        self.mock_state.avg_entry = 100.0
        self.mock_state.trailing_stop_price = 105.0
        price = 104.0 # Below TS
        atr = 1.0
        
        # Act
        logs = self.logic.process_signal(self.mock_state, price, 0, atr, {})
        
        # Assert
        self.mock_state.close_position.assert_called_with(price, "TrailingStop", ((104-100)/100))
        self.assertIn("Closed Position", logs)

if __name__ == '__main__':
    unittest.main()
