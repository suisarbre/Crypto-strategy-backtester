# Dashboard Activity Diagrams

This document visualizes the key workflows within the **Trading Dashboard** using Mermaid activity diagrams.

## 1. Dashboard Initialization & Load
This flow occurs when a user opens the dashboard in their browser.

```mermaid
flowchart TD
    Start(["User Opens URL"]) --> ConnectWS["Connect WebSocket"]
    ConnectWS --> BuildUI["Build UI Layout"]
    BuildUI --> RenderPage["Render Page Client-Side"]
    
    RenderPage --> OnPageLoad{"on_page_load Triggered"}
    
    OnPageLoad --> InitChart["Init Chart JS Component"]
    InitChart --> Delay["Small Delay (Ensure JS Ready)"]
    
    Delay --> RunBacktest[["Run Backtest Simulation"]]
    
    RunBacktest --> FetchData["Fetch History (15k candles)"]
    FetchData --> CalcStrat["Calculate Strategy Indicators & Signals"]
    CalcStrat --> SimTrade["Simulate Trades & Markers"]
    
    SimTrade --> Serialize["Serialize Data to JSON"]
    Serialize --> Push["Push to Frontend via WebSocket"]
    Push --> Display(["Chart Displayed"])
```

## 2. Live Chart Update Loop
The dashboard runs a timer (default 3s) to keep the chart in sync with the market and the bot's execution.

```mermaid
flowchart TD
    Timer(["Timer Tick (3s)"]) --> Guard{"Update in Progress?"}
    
    Guard -- Yes --> Skip(["Skip Tick"])
    Guard -- No --> SetGuard["Set Busy Flag"]
    
    SetGuard --> Fetch["Fetch Latest Data (500 candles)"]
    Fetch --> Valid{"Data Valid?"}
    
    Valid -- No --> ReleaseGuard["Clear Busy Flag"]
    Valid -- Yes --> UpdateCandle["Update Last Candle on Chart"]
    
    UpdateCandle --> SyncStatus["Sync Bot Status & Balance"]
    
    SyncStatus --> CalcMarkers["Calculate Latest Markers"]
    CalcMarkers --> Merge{"Merge Markers"}
    
    subgraph SmartMerge ["Smart Merge Logic"]
        Merge --> GetWindow["Identify New Data Time Window"]
        GetWindow --> RemoveOld["Remove Existing Markers in Window"]
        RemoveOld --> AddNew["Add New Markers"]
        AddNew --> Sort["Sort Chronologically"]
    end
    
    Sort --> PushMarkers["Push Markers to Frontend"]
    PushMarkers --> ReleaseGuard
    ReleaseGuard --> Done(["End Tick"])
```

## 3. Strategy Hot-Swap
This flow is triggered when the user selects a different strategy from the dropdown menu.

```mermaid
flowchart TD
    UserSelect(["User Selects Strategy"]) --> CheckFile{"File Exists?"}
    
    CheckFile -- No --> Error["Log Error"]
    CheckFile -- Yes --> LoadJSON["Load Strategy JSON"]
    
    LoadJSON --> UpdateInfo["Update Dashboard Info Card"]
    
    UpdateInfo --> BotAttached{"Bot Attached?"}
    
    BotAttached -- Yes --> LockBot["Acquire Bot Lock"]
    LockBot --> UpdateConfig["Update Bot Config & Strategy JSON"]
    UpdateConfig --> ReInitLogic["Re-Init Bot Strategy Logic"]
    ReInitLogic --> ReleaseLock["Release Lock"]
    
    BotAttached -- No --> SkipBot["Skip Bot"]
    ReleaseLock --> SkipBot
    
    SkipBot --> RunSim[["Run Backtest Simulation"]]
    RunSim --> UpdateChart["Update Chart & Stats"]
    UpdateChart --> Done(["Swap Complete"])
```

## 4. Bot Execution Loop (Background)
The dashboard maintains a background loop to drive the `PaperTrader` or `LiveTrader` even if no UI client is connected.

```mermaid
flowchart TD
    Start(["Background Task Start"]) --> Loop{"While True"}
    
    Loop --> CheckRunning{"Is Bot Running?"}
    
    CheckRunning -- No --> Sleep["Sleep 1s"]
    CheckRunning -- Yes --> CheckTime{"Is Candle Closed?"}
    
    CheckTime -- No --> Sleep
    CheckTime -- Yes --> Job[["Execute Trade Job"]]
    
    Job --> Log["Log Result"]
    Log --> IncTimer["Increment Next Candle Time"]
    IncTimer --> Sleep
    
    Sleep --> Loop
```
