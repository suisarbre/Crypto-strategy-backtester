"""Quick smoke test for PSO with param_defaults."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import cpp_engine
import numpy as np
import json

np.random.seed(42)
n = 300
close = np.cumsum(np.random.randn(n) * 0.001) + 100
open_ = close + np.random.randn(n) * 0.0005
high_ = np.maximum(open_, close) + np.abs(np.random.randn(n) * 0.001)
low_ = np.minimum(open_, close) - np.abs(np.random.randn(n) * 0.001)

with open('strategies/strategies.json') as f:
    strat = f.read()

res = cpp_engine.optimize_pso(
    open_, high_, low_, close,
    ['rsi_length', 'neighbors'],
    [8.0, 4.0], [20.0, 16.0],
    [14.0, 8.0],   # defaults
    strat,
    3, 500, 0.5, 100.0, 0.001, 0.99, 0.03,
    9, 8.0, 5,
    20, 10
)
print(f'PSO returned {len(res)} results')
if res:
    best = res[0]
    print(f"  Best score: {best['best_score']:.4f}, trades: {best['trades']}")
else:
    print('  No results (expected for synthetic data)')
print('Smoke test PASSED')
