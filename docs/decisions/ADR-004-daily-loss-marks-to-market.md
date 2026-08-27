# ADR-004: The daily loss limit measures equity and force-closes

Date: 2026-08-26
Status: Implemented

## Context

`TradeStateManager._check_daily_loss()` derived `loss_pct` from `self.balance`,
which only changes inside `close_position()`. An open losing position therefore
contributed **nothing** to the daily loss limit: the account could be far past
`DAILY_LOSS_LIMIT` in unrealized drawdown and the guard would never trip. The
guard could only react to losses that had already been taken.

There is a second problem that makes fixing the first one dangerous. The guard
is the first step of the ordered cascade in `process_tick()`, and it returns
early:

```python
self._check_daily_loss(price, timestamp)
if self.is_paused:
    return logs        # every guard below this is skipped
```

So pausing while a position is open abandons it — no hard stop-loss, no trailing
stop, no take-profit, forever. Under the old realized-only rule that rarely
coincided with holding a position. Marking to market makes it the *typical*
case: the guard would trip precisely when a losing position is open, and then
strand it with all risk management disabled.

`_check_daily_loss` already accepted `current_price` and ignored it.

## Decision

Three changes, which only make sense together:

1. **Measure equity, not realized balance.** `loss_pct` is computed from
   `balance + unrealized PnL`, where unrealized PnL uses the current price, the
   entry leverage, and the 50% size reduction after a partial exit — the same
   arithmetic `PaperTrader.monitor_position()` already displays.

2. **Force-close on trip.** If the limit is breached while a position is open,
   close it at the current price with reason `DailyLossLimit` before pausing.
   The guard must not leave an unmanaged position behind.

3. **Auto-resume on day change.** `is_paused` clears when the date rolls over,
   alongside the existing `daily_start_balance` reset. Without this, "daily"
   limit is a misnomer — the first bad day would permanently disable the bot,
   and in a multi-day backtest a single trip would silence every subsequent
   trade and produce an empty chart.

`is_manual_stop` is untouched by auto-resume. The kill switch stays a kill
switch and still requires an explicit `resume_trading()`.

## Consequences

- **New config invariant: `SL_RATIO` must stay below `DAILY_LOSS_LIMIT`.** Both
  are expressed as leveraged PnL, so they are directly comparable. If the stop is
  wider than the daily budget the hard stop-loss becomes unreachable — the daily
  guard fires first, closes the position with reason `DailyLossLimit`, and pauses
  for the rest of the day. The shipped config is coherent (0.03 < 0.05), and
  `tests/test_trade_state.py::test_daily_loss_preempts_a_wider_stop_loss` pins
  the precedence so a future config change surfaces it rather than silently
  disabling the stop.
- The guard now trips during open positions, which is the point, but it can trip
  on a wick — an intrabar spike that recovers still forces a real exit and stops
  trading for the rest of the day. No smoothing is applied; if this proves noisy
  the fix is a confirmation window, recorded as a new ADR.
- Backtest and marker output change. Runs that previously traded through a bad
  day now stop and show a `DailyLossLimit` exit marker. This is a behavioural
  change to historical comparisons, not a bug.
- Parity is unaffected: the C++ backtester has **no** daily-loss logic at all
  (`fast_backtest` takes no timestamps and no limit), so this rule has always
  been Python-only. It applies to live/paper trading, the chart-marker path, and
  the Python fallback backtest.
- Closing on the guard realizes the loss, so `balance` drops to roughly the
  equity value that triggered it. The account does not then re-trip on the same
  loss, because the position is flat.
- `daily_start_balance` still resets to `self.balance` on day change, so the
  next day's budget is measured from the post-loss balance.

## Alternatives rejected

- **Mark to market but only pause, don't close.** Strands an open position with
  every downstream guard disabled. Strictly worse than the old behaviour.
- **Keep realized-only.** Simple and never trips spuriously, but the guard
  cannot protect against the drawdown it exists to protect against.
- **Pause without auto-resume.** Turns a daily limit into a one-shot kill
  switch, and breaks multi-day backtest visualisation.

## Verification

`tests/test_risk_management.py` gains real assertions — it previously only
printed PASS/FAIL and asserted nothing, so pytest collected it and it always
passed regardless of behaviour.
