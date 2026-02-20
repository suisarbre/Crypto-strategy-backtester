# Sequence Diagrams

This document details the complex interactions between system components.

## 1. Strategy Hot-Swapping
This diagram shows the sequence of events when a user changes the active strategy from the Dashboard, ensuring the live bot updates without restarting.

```mermaid
sequenceDiagram
    actor User
    participant Dash as Dashboard (UI)
    participant State as TradeStateManager
    participant Loader as StrategyLoader
    participant Eng as TradingEngine
    participant Bot as CoreBot

    User->>Dash: Select "Aggressive.json"
    Dash->>State: update_config(active_strategy="Aggressive")
    
    State->>Loader: load_strategy("Aggressive")
    Loader-->>State: Returns Strategy Config/JSON
    
    State->>Eng: set_active_strategy(StrategyConfig)
    
    Note over Eng: Re-initializes Indicators<br/>and cleared Signal Logic
    
    Eng-->>State: Confirmation
    
    par Update UI
        State-->>Dash: Strategy Updated
        Dash->>User: Show "Active: Aggressive"
    and Background Log
        State->>Bot: Log "Hot Swap Complete"
    end
```

## 2. Live Trade Execution
The critical path from receiving a market tick to executing an order.

```mermaid
sequenceDiagram
    participant Clock as Heartbeat
    participant Bot as CoreBot
    participant Data as DataManager
    participant Strat as ActiveStrategy
    participant Risk as RiskManager
    participant Exch as ExchangeAPI

    Clock->>Bot: Tick (1s)
    Bot->>Data: fetch_latest_candle()
    Data-->>Bot: OHLCV DataFrame
    
    Bot->>Strat: analyze(DataFrame)
    
    Strat->>Strat: Calculate Indicators
    Strat->>Strat: Evaluate Rules (JSON)
    Strat-->>Bot: Signal (BUY/SELL)
    
    alt Signal != NEUTRAL
        Bot->>Risk: validate_signal(Signal, CurrentState)
        
        alt Risk Check Passed
            Risk-->>Bot: Approved
            Bot->>Exch: place_market_order()
            Exch-->>Bot: Order Filled (ID: 123)
            Bot->>Bot: log_trade()
        else Risk Violated
            Risk-->>Bot: Rejected (Reason: Max DD)
            Bot->>Bot: log_rejection()
        end
    else Signal == NEUTRAL
        Bot->>Bot: partial_exit_checks()
    end
```

## 3. Optimization Loop
How the `UniversalOptimizer` interacts with the `Backtester` to find the best parameters.

```mermaid
sequenceDiagram
    actor User
    participant CLI
    participant Optim as Optimizer
    participant Strat as StrategyParser
    participant Back as Backtester
    participant Gen as GeneticAlgo

    User->>CLI: optimize --strategy Standard
    CLI->>Optim: start_optimization("Standard")
    
    Optim->>Strat: get_tunable_parameters()
    Strat-->>Optim: List [RSI_Len: 10-30, SL: 1-5%]
    
    Optim->>Gen: init_population()
    
    loop Generations
        Gen->>Optim: get_next_batch(ParamsList)
        
        loop For Each ParamSet
            Optim->>Back: run_simulation(Data, ParamSet)
            Back-->>Optim: Result {Profit: 15%, DD: 5%}
        end
        
        Optim->>Gen: report_fitness(Results)
        Gen->>Gen: evolve / mutate()
        Gen-->>Optim: new_generation
    end
    
    Optim->>CLI: Best Params Found
    CLI->>User: Display Top 3 Configs
```
