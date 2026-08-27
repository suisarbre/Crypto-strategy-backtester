# ADR-005: Dashboard splits per-client view from shared application state

Date: 2026-08-26
Status: Accepted

## Context

`gui/dashboard.py` creates one module-level `TradingDashboard()` and calls
`build_ui()` on it from inside `@ui.page('/')`, which runs **once per browser
connection**:

```python
dashboard = TradingDashboard()

@ui.page('/')
async def index():
    dashboard.build_ui()
```

`build_ui()` assigns per-client UI elements — `chart`, `log_container`,
`status_label`, `strategy_select`, five buttons, three KPI labels — onto that
single shared object. Each new connection overwrites them, so the previous
client is orphaned: it renders but never updates again, because every reference
now points at the newest client's elements. Each client also starts its own
`ui.timer(1.0, self._sync_status)`, so N tabs means N timers all writing to one
label.

Three workarounds in the file exist solely to manage this:

- an aliasing check, `self.log_container.client.id != ui.context.client.id`
- a dedup guard, `self._last_loaded_client`
- a "flood protection" block that skips auto-init if the page loads more than
  three times in 30 seconds, to break an infinite refresh loop

The state inventory sorts cleanly, which is what makes this tractable: **every
UI element reference is per-client and every domain field is shared, with no
field belonging to both.**

## Decision

Split the class in two:

```python
state = DashboardState()          # module singleton: bot, is_running,
                                  # active strategy, markers, loop timing

@ui.page('/')
async def index():
    view = DashboardView(state)   # per client: owns its own UI elements
    view.build()
```

`DashboardState` imports nothing from NiceGUI. `DashboardView` holds only
element references and reads/writes `state`.

No view registry or broadcast mechanism is added. The existing design already
*polls* shared state on a `ui.timer`, so each view independently polls and
renders — which is why this refactor is a mechanical sort rather than a
redesign.

The three workarounds listed above are deleted as part of the change; if any of
them is still needed afterwards, the split was done wrong.

### Sequencing

1. **Unmask swallowed exceptions first** (separate, independently useful).
   `gui/dashboard.py` has 29 `except` blocks, 9 of them bare `pass`. Attempting
   a ~1950-line refactor while failures are invisible is not defensible.
2. Then perform the split.

## Consequences

- Multiple tabs work correctly, and a refresh stops being an event worth
  defending against.
- `DashboardState` becomes unit-testable without NiceGUI, which none of the
  dashboard logic currently is. NiceGUI is not even installed in the current
  dev environment, so this code has no test coverage at all today.
- Large mechanical diff across most of the file, with real risk of introducing
  breakage in code that presently works for a single tab. Step 1 exists to make
  that risk visible rather than silent.
- Methods that currently span both concerns must be split — `_apply_strategy()`
  reads a select, mutates the bot, and writes three labels.
- Background threads writing into client-bound elements remain a separate
  problem (see the stdout hijack note below); this ADR does not fix it.

## Alternatives rejected

- **`app.storage.client`.** Keeps one class and moves per-client fields into
  NiceGUI's client-scoped storage. Rejected because client storage requires an
  active client context, and many updates in this app originate outside one:
  `_handle_stream_message` fires from `PaperTrader` worker threads via the
  hijacked stdout, and `_trading_loop` runs in a background asyncio task. It
  also leaves the class conceptually muddled and replaces attribute access with
  stringly-typed dict lookups.
- **Single-client only** — reject or take over a second connection, making the
  shared singleton genuinely correct. Cheapest option by far (~20 lines) and
  honest about the domain, since there is no reason for two people to drive one
  bot. Rejected because refresh is the common case and the hardest to get right:
  a refresh creates the new client before the old one disconnects, so naive
  rejection locks the user out of their own dashboard. That is the same timing
  problem the flood-protection hack already fails to solve.

## Related

`TradingDashboard.__init__` replaces `sys.stdout` and `sys.stderr` at **module
import time**, because the instance is constructed at module level. Importing
`gui.dashboard` from anywhere — including a test — mutates the process globally
and never restores it. Not addressed here; worth its own ADR.
