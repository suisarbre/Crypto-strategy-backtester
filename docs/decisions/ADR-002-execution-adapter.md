# ADR-002: Order execution lives behind an ExecutionAdapter

Date: 2026-08-26
Status: Proposed

## Context

`docs/ARCHITECTURE.md` shows an "Execution Layer (Paper / Live)" that authorizes
orders against the Crypto Exchange API. **None of it exists.** A repo-wide search
for `create_order`, `place_order`, and `args.live` returns zero matches. The CLI
advertises `--live` as "Enable Live Trading (Real Money)"; `run_bot()` never
reads it. `data/data_loader.py` calls only `fetch_ohlcv()` and `fetch_ticker()`,
so the CCXT client is read-only.

Structurally there is nowhere to put an order even if we wanted one: every exit
resolves inside `TradeStateManager.close_position()`, which mutates
`self.balance` directly. There is no seam.

## Decision (proposed)

Introduce `ExecutionAdapter` with two implementations:

- `PaperAdapter` — current behaviour, mutates simulated balance.
- `LiveAdapter` — places CCXT orders and reconciles fills back into state.

`TradeStateManager` calls `self.execution.open(...)` / `.close(...)` instead of
mutating balance directly. `--live` selects the adapter; the default stays paper.

## Consequences

- `tests/test_parity.py` must pin `PaperAdapter` so Python/C++ backtest parity
  is unaffected by the indirection.
- `close_position()` currently assumes an instant, complete fill at exactly
  `price`. Live fills are asynchronous and partial. The balance arithmetic and
  the `partial_done` composite-PnL logic both assume otherwise.
- The risk cascade in `process_tick()` returns immediately after an exit fires.
  If a live order is rejected, the position is still open but the state machine
  believes it closed.
- Backtests must never be able to instantiate `LiveAdapter`.

## Open Questions

- Does a rejected live exit re-enter the risk cascade on the next tick, or halt
  the bot outright? Retrying a stop-loss into a falling market has obvious risk;
  so does leaving a position open with no stop.
- Where does fill reconciliation live — inside the adapter, or a new state that
  `process_tick()` has to understand (`PENDING_EXIT`)?
- Does the daily-loss limit measure realized balance or mark-to-market equity
  once fills are asynchronous?

## Notes

Point `LiveAdapter` at Binance testnet first. The parity tests cannot catch a
live-fill bug — they only compare two simulators to each other.
