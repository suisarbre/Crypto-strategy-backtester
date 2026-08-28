# Class Diagram

> ### 🛑 Superseded — use [`generated/CLASS_DIAGRAM.md`](generated/CLASS_DIAGRAM.md)
>
> **Audited 2026-08-26: roughly half the members below do not resolve against
> the source.** Kept only as a record of the original design intent. Regenerate
> the current one with `python tools/gen_docs.py`.
>
> Named here but **nonexistent in code**: `IStrategy` (it is `BaseStrategy`),
> `UniversalOptimizer` (`core/optimizer.py` is plain functions),
> `CppStrategyExtension` (it is the `cpp_engine` pybind11 module),
> `load_configuration()`, `run_backtest_batch()`, `update_trailing_stop()`,
> `evaluate_condition()`, `current_state`, and `PaperTrader.start()/stop()/
> _trading_loop()/hot_swap_strategy()` — the loop actually lives on
> `TradingDashboard`.
>
> **Missing entirely**: `process_tick()` (the method every tick flows through),
> `LorentzianStrategy`, `SignalEvaluator`, and the `CsvLogger` hierarchy.
>
> This file is not maintained. It rotted because hand-drawn method-level UML is
> invalidated by every refactor — which is why its replacement is generated.

This document illustrates the static structure and relationships between the main classes of the **Modular Algorithmic Trading Platform**.

```mermaid
classDiagram
    %% Core Components
    class TradingEngine {
        +analyze_market(config, timeframe) : Signal
        -fetch_data() : DataFrame
    }
    
    class TradeStateManager {
        +current_state : Dict
        +position : Position
        +balance : Float
        +open_position(side, price)
        +close_position(price)
        +update_trailing_stop(price, atr)
    }
    
    class PaperTrader {
        -engine : TradingEngine
        -state_manager : TradeStateManager
        -is_running : Boolean
        +start()
        +stop()
        +_trading_loop()
        +hot_swap_strategy(strategy_name)
    }
    
    %% Strategy Abstraction
    class IStrategy {
        <<Interface>>
        +load_configuration(config_json)
        +calculate_indicators(df)
        +generate_signal(df) : Signal, Metadata
    }
    
    class JsonStrategyLogic {
        +rules : Dictionary
        +indicators : List
        +generate_signal(df)
        -evaluate_condition(rule, row)
    }
    
    class CppStrategyExtension {
        +optimize_generic(...)
        +calculate_lorentzian(...)
    }
    
    %% UI & Control
    class TradingDashboard {
        -bot : PaperTrader
        +build_ui()
        +update_log_view()
        -on_start_click()
        -on_strategy_change()
    }
    
    %% Optimization
    class UniversalOptimizer {
        +strategy_target : IStrategy
        +execute_smart_optimization()
        -run_backtest_batch()
    }

    %% Relationships
    PaperTrader *-- TradingEngine : Composition
    PaperTrader *-- TradeStateManager : Composition
    PaperTrader o-- IStrategy : Aggregation (Swappable)
    
    JsonStrategyLogic ..|> IStrategy : Implements
    JsonStrategyLogic ..> CppStrategyExtension : Uses (Optional)
    
    TradingDashboard --> PaperTrader : Controls / Observes
    UniversalOptimizer ..> IStrategy : Inspects / Tunes
```

## Class Descriptions

1.  **PaperTrader**: The distinct "Controller" class. It owns the main loop, manages the lifecycle, and coordinates between the Engine (Data/Calc) and the State Manager (Account/Risk).
2.  **TradeStateManager**: Handles the accounting. It tracks balance, positions, and enforces risk rules like Trailing Stops. It acts as the "source of truth" for the dashboard.
3.  **IStrategy (Interface)**: The contract that all strategies must fulfill. While `JsonStrategyLogic` is the primary implementation, this abstraction allows for future Python-class-based strategies.
4.  **JsonStrategyLogic**: The concrete implementation that parses `.json` files. It converts JSON rules into executable boolean logic (e.g., "RSI < 30").
5.  **CppStrategyExtension**: Represents the high-performance C++ module (`cpp_engine`) used for intensive tasks like KNN or massive optimization loops.
