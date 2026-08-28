"""
Per-client dashboard view.

One DashboardView is constructed per browser connection and owns that client's
UI elements. Shared application state lives in gui/state.py.

Previously a single TradingDashboard instance was created at module level and
`build_ui()` was called on it from inside `@ui.page` — which runs once per
connection. Every new client overwrote the previous client's element
references, orphaning it, and three separate workarounds existed to paper over
the symptoms (a client-id alias check, a load-dedup guard, and refresh-flood
protection). All three are gone: with one view per client there is nothing to
guard against. See ADR-005.
"""
import asyncio
import mimetypes
import os
import sys

from nicegui import ui, app

import config as cfg

from gui.state import DashboardState, STATE_FIELDS, report as _report
from gui.components.chart import ChartElement
from gui.components.console import StreamRedirector, LogElement
from gui.components.layout import AppLayout
from gui.panels.optimization import OptimizationPanel
from gui.panels.benchmarks import BenchmarksPanel
from gui.panels.chart_view import ChartPanel

mimetypes.add_type('application/javascript', '.js')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app.add_static_files('/static', STATIC_DIR)


class DashboardView:
    """
    One browser client's view. Owns UI elements; shared state is delegated.

    Attribute lookup falls through to the shared DashboardState, and assignment
    to any name in STATE_FIELDS is routed there rather than shadowed locally.
    That keeps `view.bot` and `view.chart` reading naturally at every call site
    while preserving the distinction that actually matters.
    """

    def __init__(self, state):
        object.__setattr__(self, '_state', state)

        # Per-client UI elements — populated by build_ui() / AppLayout
        self.chart = None
        self.log_container = None
        self.log_expansion = None
        self.layout = None
        self.update_timer = None
        self._init_timer = None
        self.is_updating_chart = False

        # Panels hold behaviour and bind to this view
        self.optimization = OptimizationPanel(self)
        self.benchmarks = BenchmarksPanel(self)
        self.chart_panel = ChartPanel(self)

    # ── state delegation ─────────────────────────────────────────────────────

    def __getattr__(self, name):
        # Only reached when `name` isn't an instance attribute.
        try:
            return getattr(self._state, name)
        except AttributeError:
            raise AttributeError(
                f'{type(self).__name__!r} has no attribute {name!r}, '
                f'and neither does the shared DashboardState'
            ) from None

    def __setattr__(self, name, value):
        if name in STATE_FIELDS:
            setattr(self._state, name, value)
        else:
            object.__setattr__(self, name, value)

    # ── logging ──────────────────────────────────────────────────────────────

    def log(self, msg):
        """Delegate to shared state, which broadcasts to every live view."""
        self._state.log(msg)

    def push_log(self, formatted):
        """Called by DashboardState — render one line into this client's panel."""
        if self.log_container:
            self.log_container.push(formatted)

    def _clear_logs(self):
        if self.log_container:
            self.log_container.clear()

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def on_page_load(self):
        try:
            await asyncio.sleep(0.5)
            await self.chart_panel.init_chart()
        except Exception as e:
            _report('on_page_load', e)

    def dispose(self):
        self._state.detach(self)
        for timer in (self.update_timer, self._init_timer):
            try:
                if timer:
                    timer.cancel()
            except Exception as e:
                _report('dispose: timer cancel failed', e)

    # ── UI construction ──────────────────────────────────────────────────────

    def build_ui(self):
        ui.add_head_html('<script src="/static/lightweight-charts.js?v=5.1.0"></script>')
        ui.add_head_html('<script src="/static/js/chart_controller.js?v=5.1.0"></script>')

        self.layout = AppLayout(self)

        with ui.column().classes('w-full p-4 gap-3 no-wrap') \
                .style('height: calc(100vh - 50px); background: #0a0e17;'):

            with ui.row().classes('w-full gap-3 no-wrap items-stretch').style('flex-shrink: 0;'):
                self._build_kpi_card('SYMBOL', cfg.SYMBOL, icon='currency_bitcoin', color='#3b82f6')
                self._build_kpi_card('TIMEFRAME', cfg.TIMEFRAME, icon='schedule', color='#8b5cf6')
                self._kpi_leverage = self._build_kpi_card(
                    'LEVERAGE', f'{cfg.DEFAULT_LEVERAGE}x', icon='speed', color='#f59e0b')
                self._kpi_trades = self._build_kpi_card(
                    'TRADES', '0', icon='swap_vert', color='#10b981')
                self._kpi_pnl = self._build_kpi_card(
                    'SESSION P&L', '$0.00', icon='trending_up', color='#06b6d4')

            with ui.card().classes('w-full p-0 overflow-hidden chart-container') \
                    .style('flex: 1 1 0; min-height: 0;'):
                self.chart = ChartElement()

            with ui.card().classes('w-full p-0 log-panel').style('flex-shrink: 0;'):
                with ui.expansion('Activity Log', icon='terminal') \
                        .classes('w-full log-expansion') \
                        .props('dense header-class="text-gray-500"') as self.log_expansion:
                    self.log_expansion.value = False
                    self.log_container = LogElement()

            self._build_action_bar()

        self._state.attach(self)
        self.update_status_continuously()

    def _build_action_bar(self):
        buttons = [
            ('Start', 'play_arrow', 'btn-success', 'px-6', self.start_bot),
            ('Stop', 'stop', 'btn-danger', 'px-6', self.stop_bot),
            None,
            ('Optimize', 'tune', 'btn-primary', 'px-5', self.optimization.run_manual_optimization),
            ('Manual Close', 'exit_to_app', 'btn-warning', 'px-5', self.trigger_manual_close),
            None,
            ('Kill Switch', 'dangerous', 'btn-danger', 'px-5', self.trigger_kill_switch),
        ]
        with ui.element('div').classes('w-full action-bar').style('flex-shrink: 0;'):
            with ui.row().classes('w-full items-center gap-3 no-wrap justify-center'):
                for spec in buttons:
                    if spec is None:
                        ui.element('div').style('width:1px;height:28px;background:#1e293b;')
                        continue
                    label, icon, style_cls, pad, handler = spec
                    ui.button(label, on_click=handler) \
                        .props(f'unelevated icon={icon}') \
                        .classes(f'btn-modern {style_cls} text-white {pad}')

    def _build_kpi_card(self, title, value, *, icon='info', color='#3b82f6'):
        with ui.element('div').classes('kpi-card flex-1'):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.icon(icon, size='16px').style(f'color:{color};opacity:0.8;')
                ui.label(title).classes(
                    'text-[10px] font-bold tracking-widest text-gray-500 uppercase')
            return ui.label(value).classes('text-lg font-bold font-mono text-white mt-1')

    # ── strategy management ──────────────────────────────────────────────────

    def _discover_strategies(self):
        return self._state.discover_strategies()

    def _strategy_options(self):
        return self._state.strategy_options()

    def _get_strategy_info(self, path):
        return self._state.strategy_info(path)

    async def _apply_strategy(self):
        selected = self.strategy_select.value
        if not selected:
            self.log('No strategy selected')
            return

        strat_path = self.available_strategies.get(selected)
        if not strat_path or not os.path.exists(strat_path):
            self.log(f'Strategy file not found: {selected}')
            return

        self.active_strategy_name = selected
        self.active_strategy_path = strat_path

        name, version, _ = self._get_strategy_info(strat_path)
        self.strat_info_label.text = f'Active: {name} v{version}'
        self.log(f'Switching to strategy: {name} v{version}')

        if self.bot:
            with self.bot.lock:
                self.bot.state.config['active_strategy'] = selected
                try:
                    with open(strat_path, 'r') as f:
                        self.bot.state.config['strategy_json'] = f.read()
                except Exception as e:
                    self.log(f'Error loading strategy for bot: {e}')
                self.bot.state.update_config(self.bot.state.config)
            self.log(f'Bot strategy updated to: {name}')

        ran = await self.chart_panel.run_backtest_simulation()

        if ran is False:
            # Deferred: chart_markers still belong to the PREVIOUS strategy, so
            # reporting their counts here would label them as this one's.
            self.strat_stats_label.text = 'Stats: pending…'
            return

        self._update_strategy_stats()
        self.log(f'Strategy swap complete: {name}')

    def _update_strategy_stats(self):
        markers = self.chart_markers or []
        if not markers:
            return

        def count(pred):
            return sum(1 for m in markers if pred(m.get('text', '')))

        exits = ('TP', 'SL', 'TS', 'Exit', 'BE', 'TrendEnd')
        n_signals = count(lambda t: t in ('Buy', 'Sell'))
        n_entries = count(lambda t: 'LONG' in t or 'SHORT' in t)
        n_exits = count(lambda t: any(k in t for k in exits))

        self.strat_stats_label.text = (
            f'{n_signals} signals · {n_entries} entries · {n_exits} exits')

    # ── bot controls ─────────────────────────────────────────────────────────

    def start_bot(self):
        self.is_running = True
        if self.bot:
            self.bot.resume_trading()
        ui.notify('Trading started', type='positive', position='bottom-right')
        self.log('▶️ Bot resumed')

    def stop_bot(self):
        self.is_running = False
        if self.bot:
            self.bot.kill_switch()
        ui.notify('Trading stopped', type='negative', position='bottom-right')
        self.log('⏹️ Bot stopped')

    def trigger_manual_close(self):
        if self.bot:
            self.bot.manual_close()
            self.log('👋 Manual close triggered')

    def trigger_kill_switch(self):
        if self.bot:
            self.bot.kill_switch()
            ui.notify('Kill switch activated!', type='negative', position='top')
            self.log('☠️ Kill switch triggered!')

    def shutdown_app(self):
        self.log('🛑 Shutdown initiated…')
        if self.bot:
            self.bot.kill_switch()
        self.is_running = False
        ui.notify('Shutting down…', type='negative')

        async def _shutdown():
            await asyncio.sleep(1.0)
            app.shutdown()

        asyncio.create_task(_shutdown())

    # ── status & price ───────────────────────────────────────────────────────

    def update_status_continuously(self):
        ui.timer(1.0, self._sync_status)

    def _sync_status(self):
        if not self.bot:
            return

        if not self.is_running:
            label, cls = 'STOPPED', 'status-stopped'
        elif self.bot.state.is_manual_stop:
            label, cls = 'KILLED', 'status-killed'
        elif self.bot.state.is_paused:
            label, cls = 'PAUSED', 'status-paused'
        else:
            label, cls = 'RUNNING', 'status-running'

        all_cls = {'status-stopped', 'status-running', 'status-paused', 'status-killed'}
        self.status_label.text = label
        self.status_label.classes(cls, remove=' '.join(all_cls - {cls}))

    def _sync_timeframe_state(self):
        self._state.sync_timeframe()

    def _trading_loop(self):
        self._state.trading_loop()

    def update_price_label(self, price):
        self.price_label.text = f'{price:,.2f} USDT'
        if len(self.history_data) > 1:
            prev = self.history_data[-2]['close']
            color = 'text-green-400' if price >= prev else 'text-red-400'
            self.price_label.classes(color, remove='text-green-400 text-red-400')

        if not self.bot:
            return

        state = self.bot.state
        start_bal = getattr(cfg, 'START_BALANCE', 100.0)
        equity = state.equity(price) if price > 0 else state.balance
        unrealized = equity - state.balance

        roi = ((equity - start_bal) / start_bal) * 100 if start_bal else 0.0
        sign = '+' if roi >= 0 else ''

        if state.position != 0:
            self.balance_label.text = (
                f'${equity:,.2f} ({sign}{roi:.2f}%)  '
                f'[unrl: {"+" if unrealized >= 0 else ""}${unrealized:,.2f}]')
        else:
            self.balance_label.text = f'${state.balance:,.2f} ({sign}{roi:.2f}%)'

        roi_color = 'text-green-400' if roi >= 0 else 'text-red-400'
        self.balance_label.classes(
            roi_color, remove='text-green-400 text-red-400 text-gray-300')

        if getattr(self, '_kpi_pnl', None):
            pnl = equity - start_bal
            self._kpi_pnl.text = f'{"+" if pnl >= 0 else ""}${pnl:,.2f}'
            pnl_color = 'text-green-400' if pnl >= 0 else 'text-red-400'
            self._kpi_pnl.classes(pnl_color, remove='text-green-400 text-red-400 text-white')


# ==============================================================================
#  Entry point
# ==============================================================================

#: Shared across all clients. `cli.py` calls set_bot() on this.
dashboard = DashboardState()

# Capture stdout/stderr once, at import, and fan writes out to every live view.
# quiet=False so the terminal keeps receiving output — quiet=True silenced
# print() process-wide until a browser connected.
if not isinstance(sys.stdout, StreamRedirector):
    sys.stdout = StreamRedirector(sys.stdout, dashboard.handle_stream_message, quiet=False)
    sys.stderr = StreamRedirector(sys.stderr, dashboard.handle_stream_message, quiet=False)

os.makedirs('chart_data', exist_ok=True)


@ui.page('/')
async def index():
    view = DashboardView(dashboard)
    view.build_ui()

    client = ui.context.client
    # A heavy load can starve the event loop long enough for the websocket to
    # drop and NiceGUI to show "connection lost". If it reconnects the same
    # client rather than reloading the page, the view must re-register or its
    # log panel goes permanently silent.
    client.on_connect(lambda: dashboard.attach(view))
    client.on_disconnect(view.dispose)

    ui.timer(0.1, view.on_page_load, once=True)


if __name__ in {'__main__', '__mp_main__'}:
    from core.trader import PaperTrader
    import utils

    print('⚠️ Running in Standalone Mode — attaching PaperTrader…')
    utils.apply_patches()
    dashboard.set_bot(PaperTrader())

    ui.run(title='TradeBot Dashboard', dark=True, port=8080)
