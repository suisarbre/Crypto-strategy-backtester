# Dashboard Overview

The **Trading Dashboard** is a web-based user interface built with **NiceGUI** that provides real-time monitoring, strategy backtesting, and manual control over the trading bot.

## Key Features

*   **Interactive Charting**: Uses **Lightweight Charts** to display OHLCV data and trading signals.
*   **Real-time Status**: Shows the bot's current state (RUNNING, PAUSED, STOPPED), balance, and active strategy.
*   **Strategy Hot-Swapping**: Allows selecting different strategies from the `strategies/repository` and applying them instantly.
*   **Manual Controls**: Start/Stop bot, trigger manual exit, and kill switch.
*   **Live Logging**: redirection of standard output/error to a scrollable log window in the UI.

## Architecture

The dashboard is implemented in `gui/dashboard.py` and follows a component-based architecture:

```mermaid
graph TD
    User((User)) -->|HTTP/WS| NiceGUI_Server
    
    subgraph Dashboard [TradingDashboard Class]
        UI_Builder[build_ui()]
        ChartElem[ChartElement]
        LogElem[LogElement]
        
        BacktestLoop[run_backtest_simulation()]
        BackgroundLoop[run_background_loop()]
    end
    
    subgraph Core [Core System]
        Bot[PaperTrader / LiveTrader]
        Strategy[Strategy Engine]
        Data[DataFetcher]
    end
    
    NiceGUI_Server --> Dashboard
    
    Dashboard -->|set_bot()| Bot
    Dashboard -->|Fetch Data| Data
    Dashboard -->|Calculate Signals| Strategy
    
    BacktestLoop -->|Updates| ChartElem
    Bot -->|Execution Updates| LogElem
```

## Lifecycle

1.  **Startup**: `main.py` initializes the `PaperTrader` (or LiveTrader) and passes it to `dashboard.set_bot(bot)`.
2.  **Connection**: When a user connects to `http://localhost:8080`, `index()` is called, building the UI layout.
3.  **Initialization**: `on_page_load` triggers the chart initialization and the first data fetch/backtest.
4.  **Background Loop**: `run_background_loop` runs independently of connected clients to execute scheduled trading jobs (if the bot is running).
5.  **Live Updates**: `update_chart_loop` pushes new candle data and signal markers to the chart every few seconds.
