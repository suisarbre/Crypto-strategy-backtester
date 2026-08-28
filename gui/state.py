"""
Shared dashboard state — one instance per process, regardless of how many
browser clients are connected.

This is the other half of ADR-005. Everything here is genuinely global: there
is one bot, one position, one set of strategies on disk. UI elements are NOT
here — they belong to a DashboardView, one per client.
"""
import asyncio
import json
import sys
from datetime import datetime

from nicegui import app

import config as cfg
import strategies as strategies_pkg


def report(context, exc):
    """
    Surface a caught exception on the *real* stderr.

    Deliberately bypasses sys.stderr: the dashboard replaces it with a
    StreamRedirector that forwards into client-bound log elements, so an error
    raised while updating the UI would otherwise be swallowed by the very
    machinery that just failed. Never raises — reporter of last resort.
    """
    try:
        sys.__stderr__.write(f'[Dashboard] {context}: {type(exc).__name__}: {exc}\n')
        sys.__stderr__.flush()
    except Exception:
        pass


#: Attributes that belong to the process, not to a browser tab. DashboardView
#: routes assignment of these through to the shared state instead of shadowing
#: them locally — see DashboardView.__setattr__.
STATE_FIELDS = frozenset({
    'bot', 'is_running',
    'active_strategy_name', 'active_strategy_path', 'available_strategies',
    'history_data', 'chart_markers', 'current_price',
    'interval_minutes', 'next_candle_time',
    '_backtest_running', '_backtest_pending', '_backtest_start_time',
    'initial_optimization_done',
})


class DashboardState:
    """Shared application state. Holds no UI elements."""

    def __init__(self):
        self.bot = None
        self.is_running = False

        self.active_strategy_path = None
        self.active_strategy_name = getattr(cfg, 'ACTIVE_STRATEGY', 'standard')
        self.available_strategies = {}

        self.history_data = []
        self.chart_markers = []
        self.current_price = 0.0

        self.interval_minutes = 5
        self.next_candle_time = 0

        self._backtest_running = False
        self._backtest_pending = False
        self._backtest_start_time = 0
        self.initial_optimization_done = False

        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

        #: live DashboardView instances. Logging is push, not poll, so it needs
        #: a registry; everything else the views read by polling shared state.
        self.views = []

    # ── view registry ────────────────────────────────────────────────────────

    def attach(self, view):
        if view not in self.views:
            self.views.append(view)

    def detach(self, view):
        if view in self.views:
            self.views.remove(view)

    # ── logging ──────────────────────────────────────────────────────────────

    def log(self, msg):
        """Timestamp a message, broadcast it to every live view, and echo it."""
        formatted = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'

        for view in list(self.views):
            try:
                view.push_log(formatted)
            except Exception as e:
                report('log: push to a view failed', e)

        try:
            self.original_stdout.write(formatted + '\n')
            self.original_stdout.flush()
        except Exception:
            # stdout itself is gone; reporting here would recurse. Silent by design.
            pass

    def handle_stream_message(self, msg):
        """StreamRedirector callback — mirror captured stdout into the log panels."""
        if not msg.strip() or 'Candle Close' in msg or msg.startswith('\r'):
            return
        for view in list(self.views):
            try:
                view.push_log(msg.strip())
            except Exception as e:
                # Reached from PaperTrader worker threads with no client context.
                # Must never raise: this runs inside a write() call.
                report('handle_stream_message: log push failed', e)

    # ── strategy discovery ───────────────────────────────────────────────────

    def discover_strategies(self):
        """
        {key: json_path}, delegated to strategies.discover_strategies().

        Kept in one place so the GUI and the engine cannot disagree about what a
        strategy is called — they used to, which made two of four shipped
        strategies unreachable (ADR-001).
        """
        return strategies_pkg.discover_strategies()

    def strategy_options(self):
        """{key: display label} for the selector — keys stay canonical."""
        return {k: strategies_pkg.display_name(k) for k in self.discover_strategies()}

    def strategy_info(self, path):
        """(name, version, comment) from a strategy JSON."""
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return (data.get('strategy_name', 'Unknown'),
                    data.get('version', '?'),
                    data.get('comment', ''))
        except Exception as e:
            report(f'strategy_info: cannot read {path}', e)
            return ('Unknown', '?', '')

    # ── bot lifecycle ────────────────────────────────────────────────────────

    def set_bot(self, bot):
        self.bot = bot
        self.log('[OK] Bot instance attached')
        self.sync_timeframe()
        app.on_startup(lambda: asyncio.create_task(self.run_background_loop()))

    async def run_background_loop(self):
        while True:
            try:
                if self.is_running:
                    self.trading_loop()
            except Exception as e:
                report('run_background_loop', e)
            await asyncio.sleep(cfg.BACKGROUND_LOOP_INTERVAL_SEC)

    def sync_timeframe(self):
        if not self.bot:
            return
        from utils import parse_timeframe_to_minutes, get_next_candle_time

        minutes = parse_timeframe_to_minutes(self.bot.state.get_active_timeframe())
        if minutes != self.interval_minutes or self.next_candle_time == 0:
            self.interval_minutes = minutes
            self.next_candle_time = get_next_candle_time(self.interval_minutes)

    def trading_loop(self):
        if not self.bot or not self.is_running:
            return
        from utils import parse_timeframe_to_minutes
        import schedule

        active_tf = self.bot.state.get_active_timeframe()
        if parse_timeframe_to_minutes(active_tf) != self.interval_minutes:
            self.log(f'🔄 Timeframe changed: {active_tf}')
            self.sync_timeframe()

        if datetime.now().timestamp() >= self.next_candle_time:
            self.log('⚡ Executing trade job…')
            try:
                self.bot.trade_job()
            except Exception as e:
                self.log(f'❌ Trade job error: {e}')
            self.next_candle_time += self.interval_minutes * 60

        schedule.run_pending()
