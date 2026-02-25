import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from data.data_loader import fetch_raw_data, fetch_current_price

class TestDataLoader(unittest.TestCase):
    @patch('data.data_loader.exchange')
    def test_fetch_raw_data_success(self, mock_exchange):
        # Arrange
        # Mock fetch_ohlcv to return sample data
        # [timestamp, open, high, low, close, volume]
        mock_data = [
            [1672531200000, 100, 110, 90, 105, 1000], # 2023-01-01 00:00:00
            [1672532100000, 105, 115, 95, 110, 1200], # 2023-01-01 00:15:00
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_data
        mock_exchange.milliseconds.return_value = 1672534800000
        mock_exchange.parse_timeframe.return_value = 15 * 60 # 15 mins in seconds

        # Act
        df = fetch_raw_data("BTC/USDT", "15m", limit=2)
        
        # Assert
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 2)
        self.assertListEqual(df.columns.tolist(), ['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.assertEqual(df['close'].iloc[0], 105)

    @patch('data.data_loader.exchange')
    def test_fetch_raw_data_empty(self, mock_exchange):
        # Arrange
        mock_exchange.fetch_ohlcv.return_value = []
        
        # Act
        df = fetch_raw_data("BTC/USDT", "15m", limit=10)
        
        # Assert
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(df.empty)

    @patch('data.data_loader.exchange')
    def test_fetch_current_price(self, mock_exchange):
        # Arrange
        mock_exchange.fetch_ticker.return_value = {'last': 50000.0}
        
        # Act
        price = fetch_current_price("BTC/USDT")
        
        # Assert
        self.assertEqual(price, 50000.0)

    @patch('data.data_loader.exchange')
    def test_fetch_current_price_error(self, mock_exchange):
        # Arrange
        mock_exchange.fetch_ticker.side_effect = Exception("Network Error")
        
        # Act
        price = fetch_current_price("BTC/USDT")
        
        # Assert
        self.assertIsNone(price)

if __name__ == '__main__':
    unittest.main()
