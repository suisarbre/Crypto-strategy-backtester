import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from analysis.signals import generate_signals

class TestSignals(unittest.TestCase):
    def setUp(self):
        # Create a sample DataFrame used for testing
        dates = pd.date_range(start='2023-01-01', periods=100, freq='15min')
        self.df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.rand(100) * 100,
            'high': np.random.rand(100) * 105,
            'low': np.random.rand(100) * 95,
            'close': np.random.rand(100) * 100,
            'volume': np.random.rand(100) * 1000,
            # Features required for signals
            'rsi': np.random.rand(100) * 100,
            'wt1': np.random.rand(100) * 100,
            'cci': np.random.rand(100) * 100,
            'adx': np.random.rand(100) * 100,
            'ema': np.random.rand(100) * 100,
        })
        self.conf = {
            'neighbors': 5,
        }

    # Mocking cpp_engine to ensure fallback or control logic
    # But generate_signals tries to import it physically.
    # We can patch data.data_loader or sys.modules but signals.py imports cpp_engine inside try block.
    # We can control os.environ to disable it for testing Python logic.
    @patch.dict('os.environ', {'DISABLE_CPP': '1'}) 
    def test_generate_signals_python_fallback(self):
        # Arrange
        # We need strategies.json logic mocked or provided
        # generate_signals reads file if not provided.
        # Let's provide an empty strategy json to skip evaluator logic or minimal one
        minimal_strategy = '{"strategy_name": "test", "entry_rules": {"long": [], "short": []}, "exit_rules": {}}'
        
        # Act
        df_result = generate_signals(self.df, self.conf, strategy_json=minimal_strategy)
        
        # Assert
        self.assertIn('pred_signal', df_result.columns)
        self.assertIn('final_signal', df_result.columns)
        # KNN prediction should happen
        self.assertTrue(df_result['pred_signal'].isin([1, -1, 0]).all())

    @patch('analysis.signal_evaluator.SignalEvaluator')
    def test_signal_evaluator_integration(self, MockEvaluator):
        # Arrange
        mock_eval_instance = MockEvaluator.return_value
        mock_eval_instance.evaluate.return_value = pd.Series(np.ones(100))
        mock_eval_instance.evaluate_exit.return_value = pd.Series(np.zeros(100))
        
        # We need to ensure the import inside the function uses our mock
        # Since it imports from analysis.signal_evaluator, patching that module's class should work
        
        minimal_strategy = '{"mock": "strategy"}'
        
        # Act
        df_result = generate_signals(self.df, self.conf, strategy_json=minimal_strategy)
        
        # Assert
        # Check if evaluate was called. 
        # Note: generate_signals creates a new instance: evaluator = SignalEvaluator(strat_json)
        self.assertTrue(mock_eval_instance.evaluate.called)
        self.assertTrue((df_result['final_signal'] == 1).all())

if __name__ == '__main__':
    unittest.main()
