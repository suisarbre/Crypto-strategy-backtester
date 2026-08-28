# ADR-003: Leverage is fixed at 1x

Date: 2026-08-26
Status: Implemented

## Context

The project defaulted to `DEFAULT_LEVERAGE = 3` and let the optimizer search
`LEVERAGE_TEST_RANGE = [1..7]`, with a leverage-scaled fee
(`fee * entry_leverage`) in both the Python and C++ backtesters.

ADR-002 established that this has no live counterpart: `data/data_loader.py`
targets `ccxt.binanceus`, which is spot-only. Every backtest in this repo has
therefore been reporting leveraged returns that no execution path in the project
could ever reproduce.

Leverage was also a free variable in the optimizer's search space, and it is the
one parameter that inflates the fitness score without improving the underlying
signal — the optimizer is rewarded for turning it up.

## Decision

Fix leverage at **1x**. `DEFAULT_LEVERAGE = 1` and `LEVERAGE_TEST_RANGE = [1]`.

The leverage *mechanism* stays in the code — `entry_leverage` is still captured
at entry and still scales the fee — so this is a configuration decision, not a
removal. Reversing it is a one-line change.

## Consequences

- Backtest returns and max drawdown both scale down. Results are **not
  comparable** to any run recorded before 2026-08-26, including the rows already
  in `logs/optimizations.csv`.
- `leverage_fee` collapses to the base `FEE_RATE`, so fee handling in the Python
  and C++ paths becomes trivially identical.
- The optimizer search space shrinks by a factor of 7, and can no longer buy
  fitness by raising leverage instead of improving the signal.
- Resolves the backtest/live divergence ADR-002 flagged: an unleveraged spot
  live path can now, in principle, reproduce a backtest.
- `SL_RATIO = 0.03` now means a 3% move against the position rather than a 1%
  move at 3x. The stop is effectively three times wider in price terms — the
  strategy will hold losing positions longer than it used to.

## Alternatives rejected

- **Leave it at 3x and document the mismatch.** Keeps historical comparability,
  but every future backtest keeps reporting numbers the project cannot achieve.
- **Change venue to a futures exchange.** Out of scope per ADR-002; introduces a
  new API surface and jurisdictional questions this project does not need.
