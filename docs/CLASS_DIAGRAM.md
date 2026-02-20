# Class Diagram

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
