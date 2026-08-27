"""
Risk cascade tests.

These previously only printed PASS/FAIL and asserted nothing, so pytest
collected them and they passed regardless of behaviour. They now assert.
"""
import datetime
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trade_state import TradeStateManager
import config.trading as cfg


class RiskTestCase(unittest.TestCase):
    """Pins the risk config so tests don't depend on live defaults."""

    def setUp(self):
        self._saved = {
            k: getattr(cfg, k)
            for k in ('DAILY_LOSS_LIMIT', 'USE_TRAILING_STOP', 'TS_ACTIVATION',
                      'TS_CALLBACK', 'USE_BREAKEVEN', 'BE_TRIGGER', 'BE_OFFSET')
        }
        cfg.DAILY_LOSS_LIMIT = 0.05
        cfg.USE_TRAILING_STOP = True
        cfg.TS_ACTIVATION = 0.02
        cfg.TS_CALLBACK = 0.01
        cfg.USE_BREAKEVEN = True
        cfg.BE_TRIGGER = 0.015
        cfg.BE_OFFSET = 0.002

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(cfg, k, v)

    def _state(self, balance=1000.0):
        state = TradeStateManager()
        state.last_trade_date = datetime.date.today()
        state.balance = balance
        state.daily_start_balance = balance
        state.peak_balance = balance
        return state


class TestDailyLossLimit(RiskTestCase):
    def test_realized_loss_trips_the_guard(self):
        state = self._state()
        state.balance = 940.0  # -6% realized

        state._check_daily_loss(current_price=100.0)

        self.assertTrue(state.is_paused)

    def test_loss_below_limit_does_not_trip(self):
        state = self._state()
        state.balance = 970.0  # -3%

        state._check_daily_loss(current_price=100.0)

        self.assertFalse(state.is_paused)

    def test_unrealized_drawdown_trips_the_guard(self):
        """ADR-004: an open loser counts, even with balance untouched."""
        state = self._state()
        state.open_position(1, price=100.0)
        self.assertEqual(state.balance, 1000.0)

        # -8% unrealized at 1x. Balance has not moved.
        state._check_daily_loss(current_price=92.0)

        self.assertTrue(state.is_paused)

    def test_unrealized_trip_closes_the_position(self):
        """
        Pausing must not strand an open position: process_tick() returns as
        soon as is_paused is set, disabling every guard below it.
        """
        state = self._state()
        state.open_position(1, price=100.0)

        logs = state._check_daily_loss(current_price=92.0)

        self.assertEqual(state.position, 0, "position was left open after the guard tripped")
        self.assertTrue(any('DailyLossLimit' in l for l in logs), logs)
        self.assertLess(state.balance, 1000.0)

    def test_short_unrealized_drawdown_trips(self):
        state = self._state()
        state.open_position(-1, price=100.0)

        state._check_daily_loss(current_price=108.0)  # -8% on a short

        self.assertTrue(state.is_paused)
        self.assertEqual(state.position, 0)

    def test_unrealized_profit_never_trips(self):
        state = self._state()
        state.open_position(1, price=100.0)

        state._check_daily_loss(current_price=120.0)

        self.assertFalse(state.is_paused)
        self.assertEqual(state.position, 1)

    def test_process_tick_stops_trading_once_tripped(self):
        state = self._state()
        state.open_position(1, price=100.0)

        state.process_tick(92.0, signal=1)
        self.assertTrue(state.is_paused)

        # A fresh buy signal must not open anything while paused.
        state.process_tick(92.0, signal=1)
        self.assertEqual(state.position, 0)

    def test_pause_lifts_on_day_change(self):
        """Without this, a 'daily' limit is a one-shot kill switch."""
        state = self._state()
        state.balance = 940.0
        state._check_daily_loss(current_price=100.0)
        self.assertTrue(state.is_paused)

        state.last_trade_date = datetime.date.today() - datetime.timedelta(days=1)
        state._check_daily_loss(current_price=100.0)

        self.assertFalse(state.is_paused)
        self.assertEqual(state.daily_start_balance, state.balance)

    def test_day_change_does_not_lift_manual_stop(self):
        state = self._state()
        state.is_manual_stop = True
        state.last_trade_date = datetime.date.today() - datetime.timedelta(days=1)

        state._check_daily_loss(current_price=100.0)

        self.assertTrue(state.is_manual_stop, "kill switch must survive a day change")

    def test_equity_halves_after_partial_exit(self):
        state = self._state()
        state.open_position(1, price=100.0)
        state.entry_leverage = 1  # pin: this assertion is exact arithmetic
        state.partial_done = True

        # +10% on half the position -> +5% equity
        self.assertAlmostEqual(state.equity(110.0), 1050.0, places=6)

    def test_equity_scales_with_entry_leverage(self):
        state = self._state()
        state.open_position(1, price=100.0)
        state.entry_leverage = 3

        # -4% price move at 3x -> -12% equity
        self.assertAlmostEqual(state.equity(96.0), 880.0, places=6)


class TestTrailingStop(RiskTestCase):
    def test_not_activated_below_threshold(self):
        state = self._state()
        state.open_position(1, price=100.0)

        state._check_risk_management(price=101.0, atr=0)  # +1%

        self.assertEqual(state.trailing_stop_price, 0)

    def test_activates_above_threshold(self):
        state = self._state()
        state.open_position(1, price=100.0)

        state._check_risk_management(price=103.0, atr=0)  # +3%

        self.assertGreater(state.trailing_stop_price, 0)
        self.assertAlmostEqual(state.trailing_stop_price, 103.0 * 0.99, places=6)

    def test_exits_when_price_falls_through_the_trail(self):
        state = self._state()
        state.open_position(1, price=100.0)
        state._check_risk_management(price=103.0, atr=0)

        log = state._check_risk_management(price=101.0, atr=0)

        self.assertIsNotNone(log)
        self.assertIn('TrailingStop', log)
        self.assertEqual(state.position, 0)


class TestBreakeven(RiskTestCase):
    def test_stop_moves_to_breakeven(self):
        state = self._state()
        state.open_position(1, price=100.0)

        state._check_risk_management(price=101.6, atr=0)  # +1.6%

        self.assertGreaterEqual(state.trailing_stop_price, 100.2)


class TestCascadeOrder(RiskTestCase):
    def test_daily_loss_takes_precedence_over_entry(self):
        """
        The guard order in process_tick is load-bearing: a paused account must
        never reach the strategy signal.
        """
        state = self._state()
        state.balance = 940.0

        state.process_tick(100.0, signal=1)

        self.assertTrue(state.is_paused)
        self.assertEqual(state.position, 0)


if __name__ == '__main__':
    unittest.main()
