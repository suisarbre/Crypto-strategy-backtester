# ADR-002: Live execution is a separate LiveTrader over a shared risk core

Date: 2026-08-26
Status: Accepted

*(Rewritten from an earlier `Proposed` draft that recommended threading an
ExecutionAdapter through `TradeStateManager`. Editing before acceptance is what
`Proposed` is for; the rejected alternative is preserved below.)*

## Context

`docs/ARCHITECTURE.md` depicts an "Execution Layer (Paper / Live)" that
authorizes orders against the exchange. **None of it exists.** A repo-wide
search for `create_order`, `place_order`, and `args.live` returns zero matches.
`data/data_loader.py` calls only `fetch_ohlcv()` and `fetch_ticker()`, so the
CCXT client is read-only, and `run_bot()` never reads `--live`.

Structurally there is nowhere to put an order: every exit resolves inside
`TradeStateManager.close_position()`, which mutates `self.balance` directly and
assumes an instant, complete fill at exactly `price`.

**Project goal (the deciding constraint):** this is a portfolio and
proof-of-concept project. It is meant to demonstrate design and be explainable,
not to generate profit. That reprioritizes the tradeoffs — protecting the
working backtest/optimizer path and keeping the design legible matter more than
maximizing live-execution robustness.

## Decision

Live execution lives in a **separate `LiveTrader`** with its own state, rather
than as a seam threaded through `TradeStateManager`. The paper/backtest path is
not modified.

To avoid the obvious failure mode of that split — two divergent copies of the
risk rules — the guards are first **extracted into a pure `core/risk.py`** that
both paths consume:

```
core/risk.py          pure functions, no I/O, no mutation:
                      given (position, price, atr, config) -> ExitDecision | None
                      daily loss / trailing / breakeven / hard SL / TP+partial

TradeStateManager     calls risk.*, applies decisions to simulated balance
LiveTrader            calls risk.*, applies decisions as exchange orders
```

Two state machines, one risk cascade. `TradeStateManager`'s observable behaviour
must not change during the extraction — the ordering of the guards is
load-bearing and is covered by `tests/test_risk_management.py`.

**Scope: testnet only.** `LiveTrader` is a demonstration of exchange
integration. Pointing it at a mainnet account is explicitly out of scope for
this project and would require revisiting this ADR.

## Consequences

- The backtest/optimizer path and `tests/test_parity.py` are untouched. This is
  the main reason for choosing this shape.
- `core/risk.py` becomes independently unit-testable without constructing a
  `TradeStateManager`, which is a net improvement to the paper path too.
- The two state machines can still drift in ways the shared risk core does not
  prevent — position accounting, partial-exit bookkeeping, fee handling. Only
  the *rules* are shared, not the ledger. Accepted, given the goal.
- **Leverage has no live counterpart.** `data_loader.py` targets
  `ccxt.binanceus`, which is spot-only, while the project defaults to
  `DEFAULT_LEVERAGE = 3`, optimizes leverage over `[1..7]`, and charges a
  leverage-scaled fee in both backtesters. `LiveTrader` therefore runs
  unleveraged, and its results are structurally not comparable to any backtest
  in this repo. Changing venue to support futures is a separate decision and is
  not taken here.
- A rejected order is handled asymmetrically: a rejected **entry** is skipped
  and retried on the next tick; a rejected **exit** escalates (retry as market
  order N times, then halt and alert loudly). Halting while holding a position
  with no working stop is the worse failure, so exits never silently give up.
- `LiveTrader` treats the exchange as the source of truth and reconciles against
  `fetch_my_trades()` rather than assuming its local state is correct.

## Alternatives rejected

- **ExecutionAdapter threaded through `TradeStateManager`** (synchronous
  `open()`/`close()` returning real fills). Smallest diff and the right answer
  for a bot actually trading, but it puts live-order failure modes inside the
  code path the backtester shares — the wrong risk to take with the only part of
  this project that currently works well.
- **`PENDING_ENTRY`/`PENDING_EXIT` states.** Most correct model of reality, but
  every guard in the ordered cascade grows a "what if pending" branch, and the
  C++ backtester has no pending concept — parity would become structural rather
  than behavioural.
- **Full reconciliation loop as the primary design.** Most robust, largest
  change. `LiveTrader` borrows its reconciliation idea without adopting it
  repo-wide.

## Follow-up defect (independent of this ADR)

`_check_daily_loss()` computes `loss_pct` from `self.balance`, which only
changes inside `close_position()`. An open losing position therefore contributes
**nothing** to the daily loss limit — the guard cannot trip on unrealized
drawdown. This is a live defect in the current paper bot, not a live-trading
concern, and should be fixed separately.
