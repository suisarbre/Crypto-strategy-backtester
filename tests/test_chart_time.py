"""
Regression tests for chart timestamp conversion.

The dashboard used `series.astype('int64') // 10**9` to get epoch seconds,
assuming nanosecond resolution. pandas 2+ does not guarantee that:
`pd.to_datetime(x, unit='ms')` yields datetime64[ms] and the CSV cache
round-trip yields datetime64[us]. Every chart candle landed in 1970, the time
axis spanned 56 years, and the chart looked empty.
"""
import unittest

import pandas as pd

from utils import to_epoch_seconds

# 2026-08-27 01:00:00 UTC
EPOCH_S = 1787792400
EPOCH_MS = EPOCH_S * 1000


class TestToEpochSeconds(unittest.TestCase):
    def test_from_millisecond_source(self):
        """The fresh-fetch path: pd.to_datetime(unit='ms')."""
        s = pd.to_datetime(pd.Series([EPOCH_MS]), unit='ms')
        self.assertEqual(int(to_epoch_seconds(s).iloc[0]), EPOCH_S)

    def test_from_csv_roundtrip(self):
        """The cache path: written to CSV then parsed back."""
        s = pd.to_datetime(pd.Series([EPOCH_MS]), unit='ms')
        parsed = pd.to_datetime(pd.Series([str(s.iloc[0])]))
        self.assertEqual(int(to_epoch_seconds(parsed).iloc[0]), EPOCH_S)

    def test_resolution_independent(self):
        """Same answer at every datetime64 resolution."""
        base = pd.to_datetime(pd.Series([EPOCH_MS]), unit='ms')
        for unit in ('s', 'ms', 'us', 'ns'):
            with self.subTest(unit=unit):
                s = base.astype(f'datetime64[{unit}]')
                self.assertEqual(int(to_epoch_seconds(s).iloc[0]), EPOCH_S)

    def test_lands_in_the_present_not_1970(self):
        """The actual symptom: values must not collapse toward the epoch."""
        s = pd.to_datetime(pd.Series([EPOCH_MS]), unit='ms')
        got = int(to_epoch_seconds(s).iloc[0])
        self.assertGreater(got, 1_600_000_000, f'{got} is not a plausible recent timestamp')

    def test_old_approach_is_actually_wrong(self):
        """Guards the guard: proves the naive divisor still fails here."""
        s = pd.to_datetime(pd.Series([EPOCH_MS]), unit='ms')
        naive = int(s.astype('int64').iloc[0] // 10**9)
        self.assertNotEqual(naive, EPOCH_S)

    def test_spacing_is_preserved(self):
        """Truncation used to collapse distinct 5m bars onto the same second."""
        times = pd.to_datetime(
            pd.Series([EPOCH_MS, EPOCH_MS + 300_000, EPOCH_MS + 600_000]), unit='ms'
        )
        secs = to_epoch_seconds(times).tolist()
        self.assertEqual(secs, [EPOCH_S, EPOCH_S + 300, EPOCH_S + 600])
        self.assertEqual(len(set(secs)), 3)


if __name__ == '__main__':
    unittest.main()
