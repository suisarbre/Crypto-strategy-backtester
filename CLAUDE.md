# Lorentzian Trading Bot — working notes

KNN Lorentzian classification over crypto OHLCV, with a C++/pybind11 engine for
backtesting and PSO optimization, and a NiceGUI dashboard.

## Invariants — check these before changing behaviour

**The bot cannot place orders. It is paper-only.**
`data/data_loader.py` calls only `fetch_ohlcv()` and `fetch_ticker()`. There is
no order code anywhere, and the `--live` CLI flag is parsed and discarded. Do not
describe the bot as trading live. Live execution, when built, goes in a separate
`LiveTrader` over a shared `core/risk.py` — never as a seam inside
`TradeStateManager`, and testnet only. See
`docs/decisions/ADR-002-live-execution.md`.

**Leverage has no live counterpart** — `data_loader.py` targets
`ccxt.binanceus`, which is spot-only. This is why it is pinned to 1x (ADR-003);
any live path must run unleveraged.

**The risk checks in `TradeStateManager.process_tick()` are ordered, and the
order is load-bearing.**
Daily-loss pause → trailing stop / breakeven → hard stop-loss → take-profit /
partial exit → *then* the strategy signal. Each guard `return`s and ends the
tick. Never insert an early-return above the daily-loss check, and never let a
strategy open a position before the exit guards have run — routing entries
around `process_tick()` was a real bug that bypassed every risk check.

**`SL_RATIO` must stay below `DAILY_LOSS_LIMIT`** (both are leveraged PnL, so
directly comparable; currently 0.03 < 0.05). Invert that and the hard stop-loss
becomes unreachable — the daily guard fires first and additionally pauses for
the day. See ADR-004.

**The daily-loss guard measures equity, not realized balance, and force-closes
before pausing.** It has to close: `process_tick()` returns the moment
`is_paused` is set, so pausing with a position open would strand it with every
downstream guard disabled. The pause lifts on day change; `is_manual_stop` does
not. See ADR-004.

**Leverage is fixed at 1x** (ADR-003). The mechanism is still in the code and
`entry_leverage` still scales the fee — widening `LEVERAGE_TEST_RANGE` reverses
it. Backtests from before 2026-08-26 used 3x and are not comparable.

**There is exactly one live strategy instance: `TradeStateManager.logic`.**
`TradingEngine` is deliberately stateless and takes the strategy as an argument
to `analyze_market()`. It used to own a second instance, which meant a strategy
swap updated trade execution while signal generation kept running the original
`LorentzianStrategy`. Do not give `TradingEngine` a strategy attribute.

**Strategy identity is the filename stem, never the JSON's `strategy_name`.**
`regime_rider.json` → `regime_rider`. `strategy_name` is display text. Discovery
lives only in `strategies.discover_strategies()` — do not reimplement it in the
GUI. Unknown keys raise `UnknownStrategyError` rather than falling back. See
ADR-001.

**Python and C++ backtests must agree.**
`tests/test_parity.py` and `tests/test_optimizer_parity.py` enforce this. Any
change to fee handling, partial-exit composite PnL, or stop-loss arithmetic has
to land in `core/trade_state.py` *and* `cpp_extension/backtester.cpp` together.
Note the leverage-scaled fee (`fee * entry_leverage`) — it exists in both.

## Layout

```
interface/cli.py      run | optimize | dashboard
core/trader.py        PaperTrader (loop), TradingEngine (stateless analysis)
core/trade_state.py   TradeStateManager — position, balance, the risk cascade
core/optimizer.py     plain functions, not a class: execute_smart_optimization etc.
analysis/             indicators, SignalEvaluator (JSON rule engine)
strategies/           BaseStrategy + LorentzianStrategy + JsonStrategyLogic
cpp_extension/        pybind11 module `cpp_engine` — optional at every call site
gui/dashboard.py      NiceGUI; also owns the trading loop and start/stop
```

The trading loop lives on `TradingDashboard`, not on `PaperTrader`. `PaperTrader`
exposes `trade_job()`, `execute_trade_logic()`, `kill_switch()`, `manual_close()`,
`resume_trading()`.

## Docs — what to trust

| Path | Trust |
|---|---|
| `docs/decisions/` | Current. Append-only ADRs. |
| `docs/generated/` | Current. Regenerate with `python tools/gen_docs.py`. |
| `docs/cpp/`, `docs/dashboard/` | Broadly accurate. |
| `docs/ERD.md` | **Proposal, never built.** No database exists. |
| `docs/ARCHITECTURE.md` | Read path accurate; execution half is a proposal. |
| `docs/CLASS_DIAGRAM.md` | Superseded — points at `docs/generated/`. |
| `docs/GAP_ANALYSIS.md` | Historical snapshot, resolved. Do not treat as open. |

Never hand-edit anything in `docs/generated/`.

## Working style

- Real decisions get an ADR *before* the code — see `docs/decisions/README.md`.
  Bugs with one obvious fix do not.
- Prefer the fix that removes the trap over the fix that documents it. Both bugs
  above were closed by deleting a duplicate source of truth, not by adding a
  warning.
- Persistence is two CSVs under `logs/` plus strategy JSON on disk. Optimized
  params are session-only and deliberately not written back — `save_params()` /
  `load_params()` exist but their call sites are commented out.

## Environment

- Python 3.10+ (tested 3.12/3.13). C++ build: MSVC 2022 on Windows, clang/gcc
  on Linux (clang needs `libomp-dev`; `CPP_ENGINE_NO_OPENMP=1` builds without
  OpenMP). CI (`.github/workflows/ci.yml`) builds and tests both.
- `python setup.py build_ext --inplace` produces `cpp_engine.*.pyd`. Without it,
  4 test modules fail to import and the code falls back to Python/sklearn paths.
- `secret_keys.py` holds `API_KEY` / `SECRET_KEY`. Gitignored — never commit it.
- Tests: `python -m pytest tests/ -q`. Two failures are known and pre-existing
  (`test_supertrend_calculation`, and `test_execute_optimization_logic_cpp`
  without the C++ build).
