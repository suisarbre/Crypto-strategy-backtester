"""
The vectorized rational-quadratic kernel must match the original nested loop.

The loop is reproduced here verbatim as the reference implementation. If the
convolution ever diverges from it, these fail.
"""
import unittest

import numpy as np
import pandas as pd

from analysis.indicators import get_rational_quadratic_kernel, rq_weights


def reference_loop(src, lookback, relative_weight, lookback_mult=5):
    """The original O(n * lookback) implementation, unchanged."""
    y_hat = src.copy()
    src_np = src.values
    for i in range(len(src)):
        current_weight = 0.0
        cumulative_weight = 0.0
        for j in range(max(0, i - lookback * lookback_mult), i + 1):
            w = (1 + (np.power(i - j, 2) / (2 * np.power(relative_weight, 2)))) ** (-relative_weight)
            current_weight += src_np[j] * w
            cumulative_weight += w
        if cumulative_weight != 0:
            y_hat.iloc[i] = current_weight / cumulative_weight
    return y_hat


def _series(n=300, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(rng.normal(0, 1, n)) + 1000.0)


class TestKernelParity(unittest.TestCase):
    def test_matches_reference_at_defaults(self):
        s = _series()
        np.testing.assert_allclose(
            get_rational_quadratic_kernel(s, 8, 8.0, 3).to_numpy(),
            reference_loop(s, 8, 8.0, 3).to_numpy(),
            rtol=1e-9, atol=1e-9,
        )

    def test_matches_across_parameter_grid(self):
        s = _series(200, seed=7)
        for lookback in (2, 8, 20):
            for weight in (1.0, 8.0, 25.0):
                for mult in (1, 3, 5):
                    with self.subTest(lookback=lookback, weight=weight, mult=mult):
                        np.testing.assert_allclose(
                            get_rational_quadratic_kernel(s, lookback, weight, mult).to_numpy(),
                            reference_loop(s, lookback, weight, mult).to_numpy(),
                            rtol=1e-9, atol=1e-9,
                        )

    def test_window_shorter_than_lookback(self):
        """Early bars use a truncated window — the denominator must follow."""
        s = _series(5)
        np.testing.assert_allclose(
            get_rational_quadratic_kernel(s, 8, 8.0, 3).to_numpy(),
            reference_loop(s, 8, 8.0, 3).to_numpy(),
            rtol=1e-9, atol=1e-9,
        )

    def test_first_bar_is_the_source_value(self):
        """With only lag 0 available, the weighted mean is the value itself."""
        s = _series(50)
        out = get_rational_quadratic_kernel(s, 8, 8.0, 3)
        self.assertAlmostEqual(out.iloc[0], s.iloc[0], places=9)

    def test_returns_a_series_with_the_same_index(self):
        s = _series(30)
        s.index = range(100, 130)
        out = get_rational_quadratic_kernel(s, 8, 8.0, 3)
        self.assertIsInstance(out, pd.Series)
        self.assertEqual(list(out.index), list(s.index))

    def test_empty_input(self):
        self.assertEqual(len(get_rational_quadratic_kernel(pd.Series(dtype=float), 8, 8.0, 3)), 0)


class TestWeights(unittest.TestCase):
    def test_lag_zero_weight_is_one(self):
        self.assertAlmostEqual(rq_weights(8, 8.0, 3)[0], 1.0)

    def test_weights_decay_monotonically(self):
        w = rq_weights(8, 8.0, 3)
        self.assertTrue(np.all(np.diff(w) < 0))

    def test_length_is_lookback_times_mult_plus_one(self):
        self.assertEqual(len(rq_weights(8, 8.0, 3)), 8 * 3 + 1)


if __name__ == '__main__':
    unittest.main()
