"""
Regression tests for ADR-001 (strategy identity) and the hot-swap split.

Both bugs were found by comparing docs/images/*.png against the source: the
sequence diagram documented a strategy swap that propagated to both halves of
the system, and the README advertised strategies that could not actually be
selected. These tests pin the behaviour the diagrams describe.
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import strategies
from strategies.json_strategy import JsonStrategyLogic
from strategies.lorentzian import LorentzianStrategy
from core.trade_state import TradeStateManager
from core.trader import TradingEngine


class TestStrategyDiscovery(unittest.TestCase):
    def test_every_repository_json_is_reachable(self):
        """Each shipped .json resolves to a class — none silently unreachable."""
        found = strategies.discover_strategies()
        self.assertTrue(found, "no strategies discovered")

        for key in found:
            # Must not raise.
            cls = strategies.resolve_strategy_class(key)
            self.assertTrue(issubclass(cls, (JsonStrategyLogic, LorentzianStrategy)))

    def test_keys_are_filename_stems_not_display_names(self):
        """ADR-001: 'Regime Rider' is display text, 'regime_rider' is the key."""
        found = strategies.discover_strategies()

        self.assertIn('regime_rider', found)
        self.assertIn('simple', found)
        self.assertNotIn('regime rider', found)
        self.assertNotIn('robust_trend_guard', found)

    def test_keys_never_contain_spaces(self):
        for key in strategies.discover_strategies():
            self.assertNotIn(' ', key, f"strategy key '{key}' contains a space")

    def test_display_name_reads_the_json(self):
        self.assertEqual(strategies.display_name('regime_rider'), 'Regime Rider')
        self.assertEqual(strategies.display_name('simple'), 'Robust_Trend_Guard')

    def test_unknown_strategy_raises_instead_of_falling_back(self):
        """Silent fallback previously traded under a different strategy."""
        with self.assertRaises(strategies.UnknownStrategyError):
            strategies.resolve_strategy_class('does_not_exist')

    def test_json_strategies_do_not_resolve_to_lorentzian(self):
        """The old fallback returned LorentzianStrategy, ignoring the JSON rules."""
        for key in ('regime_rider', 'simple', 'aggressive'):
            self.assertIs(strategies.resolve_strategy_class(key), JsonStrategyLogic)


class TestStrategySwapPropagation(unittest.TestCase):
    """The swap must reach signal generation, not just trade execution."""

    def _df(self, n=30):
        return pd.DataFrame({
            'timestamp': pd.date_range('2023-01-01', periods=n, freq='5min'),
            'open': np.linspace(100, 110, n),
            'high': np.linspace(101, 111, n),
            'low': np.linspace(99, 109, n),
            'close': np.linspace(100, 110, n),
            'volume': np.ones(n) * 1000,
        })

    def test_engine_holds_no_strategy_of_its_own(self):
        """
        TradingEngine used to construct its own LorentzianStrategy, so a swap
        updated TradeStateManager.logic while signals kept using the engine's copy.
        """
        engine = TradingEngine()
        self.assertFalse(
            hasattr(engine, 'active_strategy'),
            "TradingEngine must not own a strategy — that reintroduces the swap split",
        )

    @patch('core.trader.fetch_raw_data')
    def test_analyze_market_uses_the_strategy_passed_in(self, mock_fetch):
        mock_fetch.return_value = self._df()

        state = TradeStateManager(config={'active_strategy': 'regime_rider'})

        captured = {}

        class _Spy:
            def calculate_indicators(self, df):
                captured['indicators'] = True
                return df

            def generate_signals(self, df):
                captured['signals'] = True
                out = df.copy()
                out['final_signal'] = 0
                out['atr'] = 1.0
                return out

        TradingEngine().analyze_market(state.config, '5m', _Spy())

        self.assertTrue(captured.get('indicators'))
        self.assertTrue(captured.get('signals'))

    def test_update_config_swaps_the_logic_instance(self):
        state = TradeStateManager(config={'active_strategy': 'standard'})
        first = state.logic

        cfg2 = dict(state.config)
        cfg2['active_strategy'] = 'regime_rider'
        state.update_config(cfg2)

        self.assertIsNot(state.logic, first, "strategy instance was not rebuilt")
        self.assertEqual(state.config['active_strategy'], 'regime_rider')

    def test_update_config_rejects_unknown_strategy(self):
        state = TradeStateManager(config={'active_strategy': 'standard'})

        cfg2 = dict(state.config)
        cfg2['active_strategy'] = 'nope'

        with self.assertRaises(strategies.UnknownStrategyError):
            state.update_config(cfg2)


if __name__ == '__main__':
    unittest.main()
