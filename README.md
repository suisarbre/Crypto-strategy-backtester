# Lorentzian Trading Bot

A cryptocurrency trading bot built around **KNN Lorentzian Classification** with a high-performance C++ engine, real-time web dashboard, and Particle Swarm Optimization (PSO).

## Overview

This project implements an automated crypto trading system that:

- Uses **KNN Lorentzian Distance** for signal classification (based on [jdehorty's TradingView indicator](https://www.tradingview.com/script/WhBzgfDu-Machine-Learning-Lorentzian-Classification/))
- Runs a **C++ engine** (via pybind11) for backtesting, optimization, and signal evaluation at native speed
- Provides a **real-time NiceGUI web dashboard** with interactive charts, live trading controls, and optimization management
- Supports **JSON-driven strategies** — add or modify entry/exit rules without touching Python code
- Optimizes parameters with **PSO (Particle Swarm Optimization)** using walk-forward analysis (IS/OOS split)

## Architecture

```
main.py                     # Entry point → routes to CLI
├── interface/cli.py        # Commands: run, optimize, dashboard
├── core/
│   ├── trader.py           # PaperTrader — live/paper trading loop
│   ├── trade_state.py      # Shared state machine (live + backtest)
│   ├── backtester.py       # Python backtester (delegates to C++ engine)
│   ├── optimizer.py        # PSO / Grid optimization orchestrator
│   └── logger.py           # CSV trade logger
├── analysis/
│   ├── indicators.py       # Technical indicators (RSI, WT, CCI, ADX, ATR, EMA, etc.)
│   ├── signals.py          # Signal generation via SignalEvaluator
│   └── signal_evaluator.py # JSON rule engine for entry/exit evaluation
├── strategies/
│   ├── base.py             # Abstract strategy interface
│   ├── json_strategy.py    # Generic JSON-driven strategy executor
│   ├── lorentzian.py       # KNN Lorentzian strategy implementation
│   └── strategies.json     # Strategy rules (entry/exit conditions)
├── data/
│   └── data_loader.py      # OHLCV data fetching via CCXT (Binance)
├── gui/
│   ├── dashboard.py        # NiceGUI web dashboard (~2000 lines)
│   └── components/         # Chart, console, layout components
├── config/
│   ├── system.py           # API keys, PSO settings, dashboard config
│   └── trading.py          # Strategy params, risk management, search spaces
├── cpp_extension/          # C++ pybind11 engine
│   ├── knn.cpp/h           # FastKNN with Lorentzian distance
│   ├── backtester.cpp/h    # fast_backtest (vectorized)
│   ├── optimizer.cpp/h     # optimize_pso, optimize_generic
│   ├── indicators.cpp/h    # C++ indicator calculations
│   ├── signal_evaluator.cpp/h  # C++ rule evaluation
│   ├── factory.cpp/h       # Indicator factory pattern
│   └── bindings.cpp        # pybind11 module definition
└── static/                 # Lightweight Charts JS for dashboard
```

## Features

### KNN Lorentzian Classification
- 5 ML features: RSI, WaveTrend, CCI, ADX, RSI(short)
- Lorentzian distance metric (better than Euclidean for financial data)
- Configurable neighbors (k), lookback window, and kernel regression filter

### Strategy System
- **Standard**: KNN signal + configurable filters (EMA trend, ADX strength, Choppiness)
- **Regime Rider**: Dual-EMA regime gate + RSI momentum filter + ADX/Choppiness for trend-following entries
- Strategies defined in JSON (`strategies/strategies.json`, `strategies/repository/`)
- Rule types: `knn_signal`, `compare`, `condition` (toggle-gated)

### C++ Engine
- **FastKNN**: Lorentzian distance KNN with OpenMP parallelization
- **fast_backtest**: Vectorized backtesting with partial exits, trailing stops, and fee modeling
- **optimize_pso**: Particle Swarm Optimization with 4-day IS / 3-day OOS validation split
- **optimize_generic**: Grid search fallback
- **IndicatorFactory + SignalEvaluator**: C++ indicator computation and JSON rule evaluation
- Build: MSVC 2022, `/O2 /std:c++17 /openmp`

### Web Dashboard
- Real-time candlestick chart with trade markers (entry/exit arrows, SL/TP lines)
- Live trading controls: Start/Stop bot, manual close position
- Optimization panel: Run PSO, view results, apply parameters, **fine-tune best results**
- Strategy & timeframe switching
- Console output with live logs

### Risk Management
- ATR-based dynamic stop loss
- Trailing stop with configurable activation and callback
- Breakeven stop (moves SL to entry + offset after profit threshold)
- Partial exit (50% at first TP hit, full exit on second)
- Daily loss limit (auto-pause trading)
- Per-trade leverage scaling

### Optimization
- PSO with walk-forward validation (4-day in-sample, 3-day out-of-sample)
- Multi-timeframe scoring with 10% improvement threshold
- Fine-tune mode: narrows search space around best result at half-step granularity
- Session-only results (no disk persistence between sessions)
- Configurable constraints: min/max trades, max MDD

## Prerequisites

- **Python 3.10+** (tested on 3.13)
- **Windows** with **MSVC 2022** (Build Tools for Visual Studio) — required for C++ extension
- **Binance US** account (for live/paper trading data)

## Setup

### 1. Clone & Virtual Environment

```bash
git clone <repo-url>
cd Finance
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install nicegui ccxt pandas numpy schedule pybind11
```

### 3. API Keys

Create `secret_keys.py` in the project root:

```python
API_KEY = 'your_binance_api_key'
SECRET_KEY = 'your_binance_secret_key'
```

> **Note**: This file is in `.gitignore` and must never be committed.

### 4. Build C++ Engine

```bash
python setup.py build_ext --inplace
```

This produces `cpp_engine.cp3XX-win_amd64.pyd` in the project root. The build requires:
- MSVC 2022 (cl.exe)
- pybind11 (installed via pip)

## Usage

### Start Dashboard (Live/Paper Trading)

```bash
python main.py run
```

Opens the web dashboard at `http://localhost:8088`. From the dashboard you can:
- Monitor live price charts with signal markers
- Start/stop the trading bot
- Run optimization and apply results
- Fine-tune optimization parameters
- Switch strategies and timeframes

### Run CLI Optimization

```bash
python main.py optimize
python main.py optimize --timeframe 15m
python main.py optimize --strategy regime_rider
```

### Dashboard Only (No Bot)

```bash
python main.py dashboard
```

## Configuration

### Trading Parameters (`config/trading.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SYMBOL` | `BTC/USDT` | Trading pair |
| `TIMEFRAME` | `5m` | Candle timeframe |
| `DEFAULT_LEVERAGE` | `3` | Default leverage |
| `SL_RATIO` | `0.03` | Stop loss ratio (3%) |
| `TP_RATIO` | `0.99` | Take profit ratio (99%) |
| `FEE_RATE` | `0.001` | Trading fee (0.1%) |
| `DAILY_LOSS_LIMIT` | `0.05` | Pause at 5% daily loss |

### System Settings (`config/system.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PSO_SWARM_SIZE` | `50` | PSO particle count |
| `PSO_MAX_ITERATIONS` | `30` | PSO generations |
| `DASHBOARD_PORT` | `8088` | Web UI port |
| `CHART_UPDATE_INTERVAL_SEC` | `10.0` | Live chart refresh rate |

### Strategy Search Space

Optimization ranges are defined in `STRATEGY_PARAMS` within `config/trading.py`. Each strategy has its own parameter grid covering ML features, filters, and risk settings.

## Testing

```bash
python -m pytest tests/ -v
```

Key test files:
- `test_trade_state.py` — State machine logic (SL, TP, partial exits)
- `test_signals.py` — Signal generation correctness
- `test_indicators.py` — Indicator calculations
- `test_parity.py` — Python/C++ engine result parity
- `test_optimizer.py` — PSO optimization flow
- `test_json_strategy.py` — JSON strategy rule parsing

## Project Documentation

> **Note:** this bot is **paper-only**. It has no order-execution code — the
> exchange connection is read-only and `--live` is not implemented. Leverage is
> simulated and has no live counterpart (`ccxt.binanceus` is spot-only). See
> [ADR-002](docs/decisions/ADR-002-live-execution.md).

Documentation is in `docs/`, in three tiers:

**Current — trust these**
- [Decision records](docs/decisions/) — append-only ADRs; why things are the way they are
- [Generated diagrams](docs/generated/) — class + module graphs, rebuilt with `python tools/gen_docs.py`
- [C++ Engine Docs](docs/cpp/) — C++ module architecture and generalization plan
- [Dashboard Docs](docs/dashboard/) — dashboard architecture and chart marking logic

**Design intent — partly aspirational, headers say which parts**
- [Architecture](docs/ARCHITECTURE.md) — accurate for the data path; execution half is a proposal
- [ERD](docs/ERD.md) — logical model; does not match the actual CSV schemas
- [PRD](docs/PRD.md) / [SRS](docs/SRS.md) — original requirements
- [Sequence Diagrams](docs/SEQUENCE_DIAGRAMS.md) — key interaction flows

**Historical**
- [Class Diagram](docs/CLASS_DIAGRAM.md) — superseded by `docs/generated/`
- [Gap Analysis](docs/GAP_ANALYSIS.md) — closed; all findings resolved

### Regenerating structure docs

```bash
python tools/gen_docs.py
```

## License

This project is for personal/educational use. Not financial advice.
