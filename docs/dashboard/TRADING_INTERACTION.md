# Trading Interaction

The Dashboard acts as a high-level controller and visualizer for the underlying Trading Engine (`PaperTrader` or `LiveTrader`).

## Bot Attachment

The dashboard does not instantiate the bot itself (except in standalone debug mode). Instead, `main.py` creates the bot and attaches it:

```python
# main.py
bot = PaperTrader()
dashboard.set_bot(bot)
```

## Control Flow

### 1. Starting & Stopping
*   **UI Action**: User clicks "Start Bot" or "Stop Bot".
*   **Dashboard**: Sets `self.is_running` flag.
*   **Bot**: Calls `bot.resume_trading()` or `bot.kill_switch()`.
    *   *Note*: `kill_switch()` is a safety feature that immediately closes all positions and pauses the bot.

### 2. Strategy Swapping
*   **UI Action**: User selects a new strategy from the dropdown.
*   **Dashboard**:
    1.  Loads the JSON file from `strategies/repository`.
    2.  Updates `bot.state.config['strategy_json']` with the new content using a thread lock to ensure safety.
    3.  Triggers `bot.state.update_config()` to re-initialize the internal logic.
    4.  Re-runs the chart backtest simulation to show the new strategy's historical performance.

### 3. Execution Loop
The dashboard maintains its own background loop (`run_background_loop`) to trigger the bot's trade job.

```python
# gui/dashboard.py
async def run_background_loop(self):
    while True:
        if self.is_running:
             # Checks candle time
             if now >= self.next_candle_time:
                 self.bot.trade_job() # <--- Triggers Core Execution
        await asyncio.sleep(1)
```

This design ensures that the dashboard UI (which can potentially freeze due to heavy rendering) does not block the critical trading execution logic.

## Data Synchronization

*   **Price & Balance**: Updated via `update_chart_loop` which polls the bot's state `bot.state.balance`.
*   **Logs**: `sys.stdout` and `sys.stderr` are intercepted by `StreamRedirector` and pushed to the dashboard's log console component, ensuring the user sees exactly what the CLI sees.
