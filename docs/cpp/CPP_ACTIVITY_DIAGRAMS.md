# C++ Engine Activity Diagrams

## 1. Top-Level Optimization Flow (`optimize_generic`)

This diagram illustrates the high-level control flow when Python calls the C++ optimizer.

```mermaid
flowchart TD
    Start(["Python Call: optimize_generic"]) --> ParseArgs["Parse Arguments & JSON Strategy"]
    ParseArgs --> GenPerm["Generate Parameter Permutations"]
    GenPerm --> ParLoop{"Parallel Loop <br/> (OpenMP)"}
    
    subgraph WorkerThread ["Worker Thread"]
        ParLoop -->|Next Combo| FeatEng[["Feature Engineering"]]
        FeatEng --> SigEval[["Signal Evaluation"]]
        SigEval --> Backtest[["Fast Backtest"]]
        Backtest --> Score["Calculate Score"]
    end
    
    Score --> CritSec{"Better than Top K?"}
    CritSec -- Yes --> UpdateList["Critical Section: Update Top Results"]
    CritSec -- No --> Continue
    
    UpdateList --> Continue["Next Iteration"]
    Continue --> ParLoop
    
    ParLoop -- Done --> Sort["Sort Top Results"]
    Sort --> Return(["Return List to Python"])
```

## 2. Feature Engineering

This section details how the optimizer dynamically computes indicators based on `strategies.json` definitions.

```mermaid
flowchart TD
    Start([Start Feature Gen]) --> LoadConf[Load Strategy Indicator Config]
    LoadConf --> Loop{For Each Indicator}
    
    Loop -->|Get Type & Params| Factory[Indicator Factory <br/> (Compute by Type)]
    Factory -->|Compute| Store[Store in Feature Map]
    
    Store --> Loop
    Loop -- Done --> ML{Has ML Model?}
    
    ML -- Yes --> TrainPredict[Train & Predict Model]
    ML -- No --> Return
    TrainPredict --> Return([Ready for Evaluator])
```

## 3. Signal Evaluation (Actually Generic)

The `SignalEvaluator` is already well-designed and generic.

```mermaid
flowchart TD
    Start(["Evaluate Candle i"]) --> CheckLong{"Check Long Entry Rules"}
    
    subgraph RuleCheck ["Rule Check (Recursive)"]
        CheckLong --> GetRule["Get Rule Logic"]
        GetRule --> ResolveLeft["Resolve Left Value <br/> (From Feature Map)"]
        GetRule --> ResolveRight["Resolve Right Value <br/> (From Feature Map or Const)"]
        ResolveLeft & ResolveRight --> Compare{"Compare <br/> (>, <, ==)"}
    end
    
    Compare -- Fail --> LongFail["Signal = 0"]
    Compare -- Pass --> NextRule{"More Rules?"}
    
    NextRule -- Yes --> GetRule
    NextRule -- No --> LongPass["Signal = 1"]
    
    LongFail --> CheckShort{"Check Short Entry Rules"}
    LongPass --> Return(["Return Signal"])
    
    CheckShort -- Pass --> ShortPass["Signal = -1"]
    CheckShort -- Fail --> ShortFail["Signal = 0"]
    
    ShortPass & ShortFail --> Return
```

## 4. Fast Backtesting

The simulated execution engine (stateless).

```mermaid
flowchart TD
    Start(["Backtest Signals"]) --> Init["Init Balance, Equity, State"]
    Init --> Loop{"For Each Candle"}
    
    Loop --> CheckExit{"Position Open?"}
    
    CheckExit -- Yes --> CheckSL{"Check Stop Loss"}
    CheckSL -- Hit --> CloseSL["Close Trade (Loss)"]
    CheckSL -- No --> CheckTP{"Check Take Profit"}
    CheckTP -- Hit --> CloseTP["Close Trade (Win)"]
    CheckTP -- No --> CheckSigExit{"Check Signal Exit"}
    
    CheckSigExit -- Exit --> CloseSig["Close Trade"]
    CheckSigExit -- No --> Hold["Hold Position"]
    
    CheckExit -- No --> CheckEntry{"Entry Signal?"}
    CheckEntry -- Yes --> OpenTrade["Open Position"]
    
    OpenTrade & CloseSL & CloseTP & CloseSig & Hold --> UpdateStats["Update MaxDD, Wins, etc"]
    
    UpdateStats --> Loop
    Loop -- Done --> CalcMetrics["Finalize Metrics"]
    CalcMetrics --> Return(["Return Result"])
```
