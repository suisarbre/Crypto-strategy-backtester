# Chart Marker Logic - Activity Diagram

This diagram illustrates the end-to-end process of generating and rendering trade markers (Buy/Sell signals) on the Dashboard Chart.

```mermaid
stateDiagram-v2
    state "Dashboard Backend (Python)" as Backend {
        [*] --> UpdateChartLoop : Timer Tick (1s) OR Strategy Swap
        
        state UpdateChartLoop {
            direction TB
            CheckGuard : Check is_updating_chart Lock
            FetchData : fetch_raw_data(Symbol, 5m)
            CalcIndicators : add_indicators() + add_dynamic_indicators()
            CalcSignals : generate_signals() (KNN/JsonStrategy)
            GenMarkers : run_backtest_with_markers()
            
            CheckGuard --> FetchData : Lock Acquired
            FetchData --> CalcIndicators : DataFrame
            CalcIndicators --> CalcSignals : DF + Indicators
            CalcSignals --> GenMarkers : DF + Signals
        }

        state "Marker Processing" as Processing {
            direction TB
            Sanitize : Convert to Python Dicts (No NaN/Inf)
            FilterWindow : Smart Merge (Replace Time Window)
            Serialize : JSON Serialization
            
            Sanitize --> FilterWindow : Clean Markers
            FilterWindow --> Serialize : Chart Data + Markers
        }
        
        UpdateChartLoop --> Processing
        
        %% Scope: Backend Cross-Boundary
        GenMarkers --> Sanitize : Raw Markers
    }

    state "Dashboard Frontend (Browser/JS)" as Frontend {
        direction TB
        RecvData : WebSocket Receive
        InitChart : Lightweight Charts v5
        
        state "Render Logic" as Render {
            CheckPlugin : Check createSeriesMarkers (v5)
            Fallback : Check series.setMarkers (v4/Compat)
            Draw : Render on Canvas
            
            CheckPlugin --> Fallback : Plugin Not Found
            CheckPlugin --> Draw : Plugin Found
            Fallback --> Draw : Method Found
        }
        
        RecvData --> Render : invoke(setMarkers)
    }
    
    %% Scope: Global Cross-Boundary
    Serialize --> RecvData : Send via NiceGUI
```

## Key Components

1.  **Backtest Simulation (`run_backtest_with_markers`)**:
    *   Replays the strategy logic over the fetched data.
    *   Generates `Entry` (LONG/SHORT) and `Exit` (TP/SL/TS/BE) events.
    *   Outputs a list of marker dictionaries: `{ time, position, color, shape, text }`.

2.  **Smart Merge Logic**:
    *   To prevent flickering or "phantom markers" during live updates, the dashboard replaces markers *only* within the simulation time window.
    *   Markers outside the window (historical) are preserved.

3.  **Frontend Rendering (v5 Migration)**:
    *   The system detects if `LightweightCharts.createSeriesMarkers` (v5 Plugin API) is available.
    *   If not, it falls back to `series.setMarkers` (Legacy API).
