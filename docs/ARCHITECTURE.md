# High-Level Architecture Diagram

> ### ⚠️ Mixed status — the execution half is a PROPOSAL
>
> **Verified 2026-08-26.** The data/analysis path below is accurate. The order
> execution path is not implemented.
>
> - **`OrderManager` / "Execution Layer (Paper / Live)" → `Exchange`: does not exist.**
>   A repo-wide search for `create_order` / `place_order` / `args.live` returns
>   zero matches. `data/data_loader.py` calls only `fetch_ohlcv()` and
>   `fetch_ticker()` — the CCXT client is **read-only**. The `--live` CLI flag is
>   parsed and silently discarded. See `docs/decisions/ADR-002-live-execution.md`,
>   which scopes live execution to a separate `LiveTrader` on testnet rather than
>   the "Execution Layer" shown below. Note also that leverage (default 3x here)
>   has no live counterpart: `ccxt.binanceus` is spot-only.
> - **`RiskManager` is not a separate component.** Risk lives inside
>   `TradeStateManager` (`_check_daily_loss`, `_check_risk_management`) and runs
>   as an ordered exit cascade *before* the strategy is consulted — not as a
>   post-signal authorization gate.
> - **`Optimizer` is PSO + grid search**, not genetic, and is a module of plain
>   functions rather than a class.
> - **Market data is polled**, not streamed — CCXT REST `fetch_ohlcv`, no websocket.
> - **`StratLoader` is the function** `strategies.discover_strategies()`.

This document illustrates the architecture of the **Modular Algorithmic Trading Platform** as defined in the PRD and SRS. It highlights the separation between the Core Execution Engine and the Pluggable Strategy System.

```flowchart TD
    %% Nodes
    User([User / Trader])
    Dashboard["Web Dashboard<br/>(NiceGUI)"]
    CLI[Command Line Interface]
    
    subgraph CoreEngine ["Core Execution Engine"]
        Heartbeat[Global Heartbeat]
        DataManager["Data Ingestion<br/>& Normalization"]
        RiskManager["Universal Risk<br/>Management"]
        OrderManager["Execution Layer<br/>(Paper / Live)"]
        StateMgr[Trade State Manager]
    end
    
    subgraph StrategySystem ["Pluggable Strategy System"]
        StratLoader[Strategy Loader]
        ActiveStrat["Active Strategy<br/>(Context)"]
        
        subgraph StrategyModules ["Strategy Modules (JSON/Python)"]
            SignalEngine[Signal Processor]
            Indicators[Indicator Library]
            AdvModules["Advanced Modules<br/>(C++ KNN / ML)"]
        end
    end
    
    Optimizer["Universal Optimizer<br/>(Genetic / Grid)"]
    
    ExternalData[("Market Data<br/>Feeds")]
    Exchange[("Crypto Exchange<br/>API")]

    %% Relationships
    User -->|Monitors & Controls| Dashboard
    User -->|Configures| CLI
    
    Dashboard <-->|WebSocket/State| StateMgr
    CLI -->|Triggers| Optimizer
    
    Heartbeat -->|Ticks| StateMgr
    
    StateMgr -->|1. Request Analysis| ActiveStrat
    ActiveStrat -->|2. Uses| SignalEngine
    SignalEngine -->|3. Calculates| Indicators
    SignalEngine -.->|Optional| AdvModules
    
    DataManager -->|OHLCV Data| StateMgr
    ExternalData -->|Stream| DataManager
    
    ActiveStrat -->|4. Returns Signal| StateMgr
    StateMgr -->|5. Validates| RiskManager
    RiskManager -->|Authorized| OrderManager
    OrderManager -->|Execute| Exchange
    
    Optimizer -->|Iterates Params| ActiveStrat
    Optimizer -->|Backtests| StateMgr
    
    StratLoader -->|Injects| ActiveStrat
```

## Component Description

1.  **Core Execution Engine**: The stable "host" application. It manages the lifecycle of the bot, connects to data sources, and handles the dirty work of order execution. It ensures that no matter what strategy is running, risk checks (Kill Switch, Daily Loss) are always enforced.
2.  **Pluggable Strategy System**: A sandbox for trading logic. Strategies are loaded dynamically. The `Signal Processor` inside this system takes standardized data (DataFrames) and returns standardized decisions (Buy/Sell/Neutral), keeping the core ignorant of *why* a trade is made.
3.  **Universal Optimizer**: Sits alongside the engine. It can take any loaded strategy, inspect its configuration (JSON), and run thousands of simulations to find the best parameter combinations (e.g., RSI Length + Stop Loss Ratio).
4.  **Interfaces**:
    *   **Dashboard**: For real-time monitoring and manual intervention.
    *   **CLI**: For headless operation and launching optimization jobs.
