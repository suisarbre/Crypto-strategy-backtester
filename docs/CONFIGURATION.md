# Configuration Reference

All values below are the shipped defaults, verified against the code on
2026-08-26. Config is split in two: `config/trading.py` holds anything that
changes results, `config/system.py` holds anything that doesn't.

## Market & data — `config/trading.py`

| Parameter | Default | Notes |
|---|---|---|
| `SYMBOL` | `BTC/USDT` | Any pair the exchange lists |
| `TIMEFRAME` | `5m` | Candle interval |
| `AVAILABLE_TIMEFRAMES` | `['5m']` | Timeframes the optimizer sweeps |
| `MAX_FETCH_LIMIT` | `15000` | Bars pulled per load. Every stage scales linearly with this — lower it for faster loads |
| `ATR_PERIOD` | `14` | ATR window used for stops |

## Account & risk — `config/trading.py`

| Parameter | Default | Notes |
|---|---|---|
| `START_BALANCE` | `100.0` | Simulated starting equity |
| `DEFAULT_LEVERAGE` | `1` | Pinned at 1x — see [ADR-003](decisions/ADR-003-leverage-fixed-at-1x.md) |
| `LEVERAGE_TEST_RANGE` | `[1]` | Widen to re-enable leverage search |
| `FEE_RATE` | `0.001` | 0.1% per side, scaled by entry leverage |
| `SL_RATIO` | `0.03` | Hard stop, as leveraged PnL. **Must stay below `DAILY_LOSS_LIMIT`** or the daily guard preempts it ([ADR-004](decisions/ADR-004-daily-loss-marks-to-market.md)) |
| `TP_RATIO` | `0.99` | First hit takes 50% off; second closes |
| `DAILY_LOSS_LIMIT` | `0.05` | Measured on **mark-to-market equity**. Force-closes and pauses until the next day |
| `USE_TRAILING_STOP` | `True` | |
| `TS_ACTIVATION` | `0.02` | Arms the trail at +2% |
| `TS_CALLBACK` | `0.01` | Trails 1% behind the high-water mark |
| `USE_BREAKEVEN` | `True` | |
| `BE_TRIGGER` | `0.015` | Moves the stop to breakeven at +1.5% |
| `BE_OFFSET` | `0.002` | Breakeven + 0.2%, to clear fees |

The order these are evaluated in is load-bearing — see the risk cascade section
in the [architecture notes](ARCHITECTURE.md).

## Optimization — `config/system.py`

| Parameter | Default | Notes |
|---|---|---|
| `USE_PSO` | `True` | Falls back to grid search if the C++ engine is missing |
| `PSO_SWARM_SIZE` | `50` | Floor — actual size scales with dimensionality |
| `PSO_MAX_ITERATIONS` | `30` | Floor — likewise |
| `WFA_WINDOW_SIZE` | `15000` | Bars in the walk-forward window |
| `WFA_TRAIN_RATIO` | `0.7` | 70% in-sample, 30% held out |
| `OPTIMIZER_MIN_TRADES` | `10` | Reject parameter sets with too few trades |
| `OPTIMIZER_MAX_MDD` | `0.3` | Reject anything drawing down more than 30% |
| `OPTIMIZE_INTERVAL_MINUTES` | `240` | Background re-optimization cadence |

## Dashboard — `config/system.py`

| Parameter | Default | Notes |
|---|---|---|
| `DASHBOARD_PORT` | `8088` | |
| `CHART_UPDATE_INTERVAL_SEC` | `10.0` | Live candle refresh |

## Search space

Per-strategy parameter ranges live in `STRATEGY_PARAMS` in `config/trading.py`.
Each entry is either an explicit list of values or a `{'type': 'dynamic', ...}`
window that the optimizer centres on the current value.

## API credentials

**Not required.** Only public CCXT endpoints are used (`fetch_ohlcv`,
`fetch_ticker`). If `secret_keys.py` is absent the exchange client is built
without credentials. See [ADR-002](decisions/ADR-002-live-execution.md).
