"""
Tests for the chart pipeline.

None of this was testable before: it lived as a closure (`_heavy_loader`)
inside a 174-line NiceGUI method, which is why the datetime-resolution bug
that put every candle in 1970 went unnoticed.
"""
import unittest

import numpy as np
import pandas as pd

from gui.panels.chart_data import to_candles, clean_marker, _finite

EPOCH_S = 1787792400
EPOCH_MS = EPOCH_S * 1000


def _df(n=5):
    return pd.DataFrame({
        'timestamp': pd.to_datetime(
            pd.Series([EPOCH_MS + i * 300_000 for i in range(n)]), unit='ms'),
        'open': np.linspace(100, 104, n),
        'high': np.linspace(101, 105, n),
        'low': np.linspace(99, 103, n),
        'close': np.linspace(100, 104, n),
    })


class TestFinite(unittest.TestCase):
    def test_passes_normal_values(self):
        self.assertEqual(_finite(1.5), 1.5)

    def test_nan_becomes_none(self):
        self.assertIsNone(_finite(float('nan')))

    def test_infinities_become_none(self):
        self.assertIsNone(_finite(float('inf')))
        self.assertIsNone(_finite(float('-inf')))


class TestToCandles(unittest.TestCase):
    def test_shape_and_keys(self):
        c = to_candles(_df())
        self.assertEqual(len(c), 5)
        self.assertEqual(set(c[0]), {'time', 'open', 'high', 'low', 'close'})

    def test_times_are_epoch_seconds_not_1970(self):
        c = to_candles(_df())
        self.assertEqual(c[0]['time'], EPOCH_S)
        self.assertGreater(c[0]['time'], 1_600_000_000)

    def test_five_minute_spacing_preserved(self):
        times = [c['time'] for c in to_candles(_df(3))]
        self.assertEqual(times, [EPOCH_S, EPOCH_S + 300, EPOCH_S + 600])

    def test_times_are_ints(self):
        for c in to_candles(_df()):
            self.assertIsInstance(c['time'], int)

    def test_nan_prices_become_none(self):
        df = _df()
        df.loc[2, 'close'] = float('nan')
        self.assertIsNone(to_candles(df)[2]['close'])

    def test_survives_the_csv_cache_roundtrip(self):
        """The cache path yields datetime64[us], a different wrong divisor."""
        df = _df()
        df['timestamp'] = pd.to_datetime(df['timestamp'].astype(str))
        self.assertEqual(to_candles(df)[0]['time'], EPOCH_S)


class TestCleanMarker(unittest.TestCase):
    def test_coerces_to_json_safe_primitives(self):
        m = clean_marker({
            'time': np.int64(EPOCH_S), 'position': 'belowBar',
            'color': '#21ba45', 'shape': 'arrowUp', 'text': 'LONG',
        })
        self.assertIsInstance(m['time'], int)
        self.assertEqual(m['text'], 'LONG')

    def test_missing_text_defaults_to_empty(self):
        m = clean_marker({'time': 1, 'position': 'aboveBar',
                          'color': '#fff', 'shape': 'circle'})
        self.assertEqual(m['text'], '')


if __name__ == '__main__':
    unittest.main()
