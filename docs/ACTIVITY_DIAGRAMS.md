# Activity Diagrams

This document details the key workflows of the **Modular Algorithmic Trading Platform**.

## 1. Core Trading Loop
This diagram illustrates the main execution cycle that occurs on every "Heartbeat" (Tick/Candle Close). It shows how the Core Engine interacts with the Pluggable Strategy and Risk Management layers.

```mermaid
flowchart TD
    Start(("Start Tick")) --> FetchData["Fetch OHLCV Data"]
    FetchData --> NormData["Normalize Data"]
    NormData --> UpdateState["Update Trade State"]
    
    subgraph Strategy ["Strategy Execution"]
        UpdateState --> CalcInd["Calculate Indicators"]
        CalcInd --> RunLogic["Run Strategy Logic"]
        RunLogic --> GenSignal{"Signal Generated?"}
    end
    
    GenSignal -- No Signal --> End(("Wait Next Tick"))
    GenSignal -- Buy/Sell --> RiskCheck{"Risk Check"}
    
    subgraph Risk ["Risk Management"]
        RiskCheck -- "Violation (Max DD / Kill Switch)" --> Reject["Reject Signal"]
        RiskCheck -- Safe --> CheckPos{"Current Position?"}
    end
    
    Reject --> LogReject["Log Rejection"] --> End
    
    CheckPos -- Same Direction --> End
    CheckPos -- Opposite Direction --> ClosePos["Close Current Position"]
    CheckPos -- No Position --> OpenPos["Open New Position"]
    ClosePos --> OpenPos
    
    OpenPos --> Execute["Execute Order (Paper/Live)"]
    Execute --> LogTrade["Log Trade"] --> End
```

## 2. Optimization Workflow
This diagram depicts the Universal Optimization process, highlighting how the system adapts to different strategies and optimizes parameters using a genetic or grid-based approach.

```mermaid
flowchart TD
    Start(("User Start")) --> LoadStrat["Load Strategy JSON"]
    LoadStrat --> Inspect["Inspect Parameters & Ranges"]
    Inspect --> GenPop["Generate Initial Population"]
    
    subgraph SimLoop ["Simulation Loop"]
        GenPop --> SelectParams["Select Parameter Set"]
        SelectParams --> FetchHist["Fetch Historical Data"]
        FetchHist --> RunBacktest["Run Backtest"]
        RunBacktest --> CalcMetric["Calculate Fitness<br/>(Profit * Sharpe)"]
        CalcMetric --> Converged{"Converged?"}
    end
    
    Converged -- No --> Evolve["Evolve / Mutate"] --> GenPop
    Converged -- Yes --> WalkForward{"Walk-Forward Required?"}
    
    WalkForward -- Yes --> SplitData["Split In-Sample / Out-of-Sample"]
    SplitData --> TestOOS["Test Best Params on OOS Data"]
    TestOOS --> Validate{"Pass OOS Threshold?"}
    
    Validate -- Fail --> Discard["Discard Params"] --> ReportFail["Report Failure"]
    Validate -- Pass --> Save["Save Best Parameters"]
    WalkForward -- No --> Save
    
    Save --> End(("End"))
    ReportFail --> End
```

## 3. Signal Evaluation Logic (Example: Lorentzian)
This diagram details the internal logic of a sophisticated strategy (like Lorentzian) to show how multiple components (KNN, Filters, Thresholds) combine to produce a final signal.

```mermaid
flowchart TD
    Start(("Input Data")) --> PreProcess["Preprocessing"]
    
    subgraph Features ["Feature Engineering"]
        PreProcess --> CalcRSI["Calculate RSI"]
        PreProcess --> CalcADX["Calculate ADX"]
        PreProcess --> CalcCCI["Calculate CCI"]
    end
    
    subgraph ML_Logic ["Machine Learning (KNN)"]
        Features --> CalcDist["Calculate Lorentzian Distance"]
        CalcDist --> FindNeighbors["Find k-Nearest Neighbors"]
        FindNeighbors --> PredPrice["Predict Price Movement"]
        PredPrice --> RawSignal["Raw ML Signal"]
    end
    
    subgraph Filters ["Confirmation Filters"]
        RawSignal --> CheckTrend{"EMA Trend Aligned?"}
        CheckTrend -- No --> Neutral["Signal: Neutral"]
        CheckTrend -- Yes --> CheckVol{"Volatility < Threshold?"}
        CheckVol -- "No (Choppy)" --> Neutral
        CheckVol -- Yes --> CheckStr{"ADX > Threshold?"}
        CheckStr -- "No (Weak)" --> Neutral
    end
    
    CheckStr -- Yes --> FinalSignal["Signal: Buy/Sell"]
    Neutral --> Output(("Output Signal"))
    FinalSignal --> Output
```
