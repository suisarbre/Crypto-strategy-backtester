# Entity Relationship Diagram (ERD)

This document visualizes the data entities and their relationships within the **Modular Algorithmic Trading Platform**. Since the system currently uses CSV files and JSON configuration rather than a relational database, this diagram represents the *logical* data model.

```mermaid
erDiagram
    %% Entities
    STRATEGY_CONFIG {
        string name PK "Unique Strategy Name"
        string version
        json parameters "Indicators, Thresholds"
        json rules "Entry/Exit Conditions"
    }

    TRADE_LOG {
        int id PK "Auto-increment ID"
        timestamp entry_time
        timestamp exit_time
        string symbol
        string direction "LONG/SHORT"
        float entry_price
        float exit_price
        float size
        float pnl "Profit/Loss"
        float balance_after
        string exit_reason "TP/SL/Signal"
        string strategy_name FK
    }

    OPTIMIZATION_RESULT {
        int id PK
        timestamp run_time
        string strategy_name FK
        json parameters "Best Params Found"
        float win_rate
        float total_return
        float max_drawdown
        float sharpe_ratio
        string timeframe
    }

    PORTFOLIO_STATE {
        string account_id PK
        float current_balance
        float locked_balance
        json active_positions
        timestamp last_updated
    }

    %% Relationships
    STRATEGY_CONFIG ||--o{ TRADE_LOG : "generates"
    STRATEGY_CONFIG ||--o{ OPTIMIZATION_RESULT : "tuned_via"
    PORTFOLIO_STATE ||--o{ TRADE_LOG : "records_history"
```

## Data Entity Descriptions

1.  **STRATEGY_CONFIG**: Represents the JSON files located in `strategies/`. It is the blueprint for trading logic.
    *   *Storage*: `strategies/*.json`
2.  **TRADE_LOG**: The historical record of all executed trades. This is the primary source for performance analysis.
    *   *Storage*: `trades.csv` (and potentially `logs/app.log` for unstructured data).
3.  **OPTIMIZATION_RESULT**: Stores the outcomes of genetic algorithm runs, allowing the user to pick the best customization for a strategy.
    *   *Storage*: `optimizations.csv`
4.  **PORTFOLIO_STATE**: The live snapshot of the user's account. While currently transient (in-memory `TradeStateManager`), in a production database it would be a persistent table.
    *   *Storage*: In-Memory (runtime).
