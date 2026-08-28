import os
import sys
import json
import asyncio
import random
import time
import mimetypes
from datetime import datetime

import pandas as pd

from nicegui import ui, app
import config as cfg
import strategies as strategies_pkg

# Local Modules
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals

# Components
from gui.components.chart import ChartElement
from gui.components.console import StreamRedirector, LogElement
from gui.components.layout import AppLayout

# Panels — behaviour split out of this module; state still lives here (ADR-005)
from gui.panels.optimization import OptimizationPanel

# ==============================================================================
# 1.  System Configuration
# ==============================================================================

mimetypes.add_type('application/javascript', '.js')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app.add_static_files('/static', STATIC_DIR)


def _report(context, exc):
    """
    Surface a caught exception on the *real* stderr.

    Deliberately bypasses sys.stderr: TradingDashboard replaces it with a
    StreamRedirector that forwards into a client-bound log element, so an error
    raised while updating the UI would otherwise be swallowed by the very
    machinery that just failed. Never raises — this is the reporter of last
    resort.
    """
    try:
        sys.__stderr__.write(f'[Dashboard] {context}: {type(exc).__name__}: {exc}\n')
        sys.__stderr__.flush()
    except Exception:
        pass


# ==============================================================================
# 2.  Main Dashboard Class
# ==============================================================================

class TradingDashboard:
    def __init__(self):
        self.is_running = False
        self.client_connected = False
        self.history_data = []
        self.chart = None
        self.bot = None

        # Strategy swap state
        self.active_strategy_path = None
        self.active_strategy_name = (
            cfg.ACTIVE_STRATEGY if hasattr(cfg, 'ACTIVE_STRATEGY') else 'standard'
        )
        self.available_strategies = {}

        # Panels own behaviour, not state — see gui/panels/
        self.optimization = OptimizationPanel(self)

        os.makedirs('chart_data', exist_ok=True)

        # Log redirection
        if not isinstance(sys.stdout, StreamRedirector):
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            # quiet=False so the terminal keeps receiving output. With quiet=True
            # StreamRedirector.write() never forwarded to the real stream, so
            # importing this module silenced print() process-wide until a browser
            # client connected — which made the dashboard impossible to
            # print-debug, and also swallowed monitor_position's live status line.
            sys.stdout = StreamRedirector(sys.stdout, self._handle_stream_message, quiet=False)
            sys.stderr = StreamRedirector(sys.stderr, self._handle_stream_message, quiet=False)
        else:
            sys.stdout.callback = self._handle_stream_message
            sys.stderr.callback = self._handle_stream_message

    # ──────────────────────────────────────────────────────────────────────────
    #  Stream → UI bridge
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_stream_message(self, msg):
        if not msg.strip():
            return
        if 'Candle Close' in msg:
            return
        if msg.startswith('\r'):
            return
        if getattr(self, 'client_connected', False):
            try:
                if hasattr(self, 'log_container') and self.log_container:
                    self.log_container.push(msg.strip())
            except Exception as e:
                # Reached from PaperTrader worker threads via the stdout hijack,
                # i.e. with no client context. Reported, not raised: this runs
                # inside a write() and must never break the caller's print().
                _report('_handle_stream_message: log push failed', e)

    # ──────────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def set_bot(self, bot):
        self.bot = bot
        self.log('[OK] Bot instance attached')
        self.interval_minutes = 5
        self.next_candle_time = 0
        self._sync_timeframe_state()
        app.on_startup(lambda: asyncio.create_task(self.run_background_loop()))

    async def on_page_load(self):
        try:
            if (
                not hasattr(self, 'log_container')
                or self.log_container.client.id != ui.context.client.id
            ):
                return

            # Skip if we already loaded for this client session
            current_client_id = ui.context.client.id
            if getattr(self, '_last_loaded_client', None) == current_client_id:
                return
            self._last_loaded_client = current_client_id

            # ── Flood protection: if the page loads too often, skip auto-init
            #    to break an infinite refresh loop. ──
            now = time.time()
            if not hasattr(self, '_page_load_times'):
                self._page_load_times = []
            self._page_load_times.append(now)
            # Keep only loads within the last 30 seconds
            self._page_load_times = [t for t in self._page_load_times if now - t < 30]
            if len(self._page_load_times) > 3:
                print(f'[Dashboard] Page loaded {len(self._page_load_times)}× in 30s — '
                      f'skipping auto-init to break refresh loop')
                self.client_connected = True
                return

            # ── Reset stale backtest_running flag from a crashed/interrupted run ──
            if getattr(self, '_backtest_running', False):
                elapsed = now - getattr(self, '_backtest_start_time', 0)
                if elapsed > 120:  # 2 minutes → definitely stale
                    print('[Dashboard] Resetting stale _backtest_running flag')
                    self._backtest_running = False
                    self._backtest_pending = False

            self.client_connected = True
            await asyncio.sleep(0.5)
            await self.init_chart()
        except Exception as e:
            print(f'Error in on_page_load: {e}')

    async def run_background_loop(self):
        while True:
            try:
                if self.is_running:
                    self._trading_loop()
            except Exception as e:
                print(f'Background loop error: {e}')
            await asyncio.sleep(cfg.BACKGROUND_LOOP_INTERVAL_SEC)

    # ──────────────────────────────────────────────────────────────────────────
    #  UI Construction
    # ──────────────────────────────────────────────────────────────────────────

    def build_ui(self):
        # Static files
        app.add_static_files('/static', 'static')
        ui.add_head_html('<script src="/static/lightweight-charts.js?v=5.1.0"></script>')
        ui.add_head_html('<script src="/static/js/chart_controller.js?v=5.1.0"></script>')

        # Layout shell (header + sidebar with strategy/chart tools)
        self.layout = AppLayout(self)

        # ══════════════════════════════════════════════════════════════════════
        #  MAIN CONTENT AREA
        # ══════════════════════════════════════════════════════════════════════
        with ui.column().classes('w-full p-4 gap-3 no-wrap') \
                .style('height: calc(100vh - 50px); background: #0a0e17;'):

            # ── KPI Cards Row ──
            with ui.row().classes('w-full gap-3 no-wrap items-stretch') \
                    .style('flex-shrink: 0;'):
                self._build_kpi_card('SYMBOL', cfg.SYMBOL, icon='currency_bitcoin', color='#3b82f6')
                self._build_kpi_card('TIMEFRAME', cfg.TIMEFRAME, icon='schedule', color='#8b5cf6')
                self._kpi_leverage = self._build_kpi_card('LEVERAGE', f'{cfg.DEFAULT_LEVERAGE}x', icon='speed', color='#f59e0b')
                self._kpi_trades = self._build_kpi_card('TRADES', '0', icon='swap_vert', color='#10b981')
                self._kpi_pnl = self._build_kpi_card('SESSION P&L', '$0.00', icon='trending_up', color='#06b6d4')

            # ── Chart (takes ALL remaining vertical space) ──
            with ui.card().classes('w-full p-0 overflow-hidden chart-container') \
                    .style('flex: 1 1 0; min-height: 0;'):
                self.chart = ChartElement()

            # ── Activity Log (collapsible — closed by default) ──
            with ui.card().classes('w-full p-0 log-panel').style('flex-shrink: 0;'):
                with ui.expansion('Activity Log', icon='terminal') \
                        .classes('w-full log-expansion') \
                        .props('dense header-class="text-gray-500"') as self.log_expansion:
                    self.log_expansion.value = False  # collapsed by default
                    self.log_container = LogElement()

            # ── Bottom Action Bar ──
            with ui.element('div').classes('w-full action-bar').style('flex-shrink: 0;'):
                with ui.row().classes('w-full items-center gap-3 no-wrap justify-center'):
                    self.btn_start = (
                        ui.button('Start', on_click=self.start_bot)
                        .props('unelevated icon=play_arrow')
                        .classes('btn-modern btn-success text-white px-6')
                    )
                    self.btn_stop = (
                        ui.button('Stop', on_click=self.stop_bot)
                        .props('unelevated icon=stop')
                        .classes('btn-modern btn-danger text-white px-6')
                    )

                    # Vertical divider
                    ui.element('div').style('width:1px;height:28px;background:#1e293b;')

                    self.btn_optimize = (
                        ui.button('Optimize', on_click=self.optimization.run_manual_optimization)
                        .props('unelevated icon=tune')
                        .classes('btn-modern btn-primary text-white px-5')
                    )
                    self.btn_manual_close = (
                        ui.button('Manual Close', on_click=self.trigger_manual_close)
                        .props('unelevated icon=exit_to_app')
                        .classes('btn-modern btn-warning text-white px-5')
                    )

                    ui.element('div').style('width:1px;height:28px;background:#1e293b;')

                    self.btn_kill = (
                        ui.button('Kill Switch', on_click=self.trigger_kill_switch)
                        .props('unelevated icon=dangerous')
                        .classes('btn-modern btn-danger text-white px-5')
                    )

        # Status update loop
        self.update_status_continuously()

    # ──────────────────────────────────────────────────────────────────────────
    #  KPI Card Builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_kpi_card(self, title, value, *, icon='info', color='#3b82f6'):
        with ui.element('div').classes('kpi-card flex-1'):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.icon(icon, size='16px').style(f'color:{color};opacity:0.8;')
                ui.label(title).classes('text-[10px] font-bold tracking-widest text-gray-500 uppercase')
            value_label = ui.label(value).classes('text-lg font-bold font-mono text-white mt-1')
        return value_label

    def _clear_logs(self):
        if hasattr(self, 'log_container') and self.log_container:
            self.log_container.clear()

    # ──────────────────────────────────────────────────────────────────────────
    #  Benchmark Panel Builder
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_benchmarks(self, df, config):
        """
        Run the C++ backtest to get strategy metrics and compute buy-and-hold
        baseline for comparison.  Returns (strategy_metrics, baseline_metrics).
        """
        import numpy as np

        # ── Trim to last 7 days of data ──
        tf_minutes = self._tf_to_minutes(cfg.TIMEFRAME)
        bars_per_day = 1440.0 / tf_minutes
        bars_7d = int(bars_per_day * 7)
        if len(df) > bars_7d:
            df = df.tail(bars_7d).copy().reset_index(drop=True)

        prices = df['close'].values.astype(np.float64)
        signals = df['final_signal'].values.astype(np.int32)
        atr_vec = df['atr'].values.astype(np.float64)

        leverage = int(config.get('leverage', 1))
        sl_ratio  = float(config.get('sl_ratio', 0.03))
        tp_ratio  = float(config.get('tp_ratio', 0.8))
        sl_mult   = float(config.get('sl_multiplier', 0.0))
        start_bal = float(getattr(cfg, 'START_BALANCE', 100.0))
        fee_rate  = float(getattr(cfg, 'FEE_RATE', 0.001))

        if 'exit_signal' in df.columns:
            exit_signals = df['exit_signal'].values.astype(np.int32)
        else:
            exit_signals = np.zeros(len(df), dtype=np.int32)

        try:
            import cpp_engine
            res = cpp_engine.fast_backtest(
                prices, signals, exit_signals, atr_vec,
                leverage, start_bal, sl_ratio, sl_mult, tp_ratio, fee_rate,
            )
        except ImportError:
            # Fall back to the Python backtester rather than returning nothing.
            # Requiring the C++ build here left the benchmark drawer permanently
            # empty for anyone who had not run `setup.py build_ext`, which read
            # as "the benchmark button does not work".
            from core.backtester import run_deep_backtest
            balance, wins, trades, mdd, _ = run_deep_backtest(df, config)
            res = {
                'balance': balance,
                'wins': wins,
                'trades': trades,
                'mdd': mdd,
                'total_return': (balance - start_bal) / start_bal if start_bal else 0.0,
                # Risk-adjusted ratios come from the C++ engine only.
                'sortino': None,
                'calmar': None,
                'profit_factor': None,
            }

        def _pct(v):
            return v * 100 if v is not None else None

        strategy = {
            'total_return': _pct(res.get('total_return', 0.0)),
            'sortino':       res.get('sortino', 0.0),
            'calmar':        res.get('calmar', 0.0),
            'profit_factor': res.get('profit_factor', 0.0),
            'mdd':           _pct(res.get('mdd', 0.0)),
            'trades':        res.get('trades', 0),
            'wins':          res.get('wins', 0),
            'win_rate':      (res['wins'] / res['trades'] * 100) if res.get('trades', 0) > 0 else 0.0,
            'balance':       res.get('balance', start_bal),
            'engine':        'cpp' if res.get('sortino') is not None else 'python',
        }

        # Buy-and-Hold baseline
        if len(prices) > 1:
            bh_return = (prices[-1] - prices[0]) / prices[0] * 100
        else:
            bh_return = 0.0

        # Risk-free rate proxy (annualised ~4.5% → scale to data window)
        # Estimate data duration in years from bar count & timeframe
        tf_minutes = self._tf_to_minutes(cfg.TIMEFRAME)
        data_hours = len(prices) * tf_minutes / 60.0
        data_years = data_hours / (365.25 * 24)
        risk_free_annual = 4.5  # %
        risk_free_period = risk_free_annual * data_years

        baseline = {
            'buy_hold_return': bh_return,
            'risk_free_return': risk_free_period,
            'risk_free_annual': risk_free_annual,
            'data_years':       data_years,
        }

        return strategy, baseline

    @staticmethod
    def _tf_to_minutes(tf_str: str) -> float:
        """Convert a timeframe string like '15m', '1h', '4h', '1d' to minutes."""
        tf = tf_str.strip().lower()
        if tf.endswith('m'):
            return float(tf[:-1])
        if tf.endswith('h'):
            return float(tf[:-1]) * 60
        if tf.endswith('d'):
            return float(tf[:-1]) * 1440
        if tf.endswith('w'):
            return float(tf[:-1]) * 10080
        return 15.0  # fallback

    def _populate_benchmarks(self, strategy, baseline):
        """Rebuild the benchmark drawer contents with fresh data."""
        if not hasattr(self, 'bench_container'):
            return

        self.bench_container.clear()

        alpha = strategy['total_return'] - baseline['buy_hold_return']
        rf_alpha = strategy['total_return'] - baseline['risk_free_return']

        with self.bench_container:
            # ── Alpha Badge ──
            alpha_cls = 'alpha-positive' if alpha >= 0 else 'alpha-negative'
            alpha_sign = '+' if alpha >= 0 else ''
            with ui.element('div').classes(f'w-full alpha-badge {alpha_cls}'):
                ui.label(f'α  {alpha_sign}{alpha:.2f}%').style('margin:0;')

            ui.separator().classes('my-1')

            # ── Section: Strategy Performance ──
            ui.label('STRATEGY PERFORMANCE').classes('bench-header')

            # Ratios are C++-engine only; show why they're absent rather than
            # rendering a misleading 0.000.
            cpp_only = strategy.get('engine') != 'cpp'

            def _ratio(value, fmt):
                return 'n/a' if value is None else format(value, fmt)

            ratio_sub = 'needs C++ engine' if cpp_only else None

            self._bench_row('Total Return', f'{strategy["total_return"]:+.2f}%',
                            color='#10b981' if strategy['total_return'] >= 0 else '#ef4444')
            self._bench_row('Sortino Ratio', _ratio(strategy['sortino'], '.3f'),
                            sub=ratio_sub or 'risk-adjusted return', color='#3b82f6')
            self._bench_row('Calmar Ratio', _ratio(strategy['calmar'], '.3f'),
                            sub=ratio_sub or 'return / max DD', color='#8b5cf6')
            self._bench_row('Profit Factor', _ratio(strategy['profit_factor'], '.2f'),
                            sub=ratio_sub or 'gross P / gross L', color='#f59e0b')
            self._bench_row('Max Drawdown', f'{strategy["mdd"]:.2f}%',
                            color='#ef4444')
            self._bench_row('Win Rate', f'{strategy["win_rate"]:.1f}%',
                            sub=f'{strategy["wins"]}/{strategy["trades"]} trades',
                            color='#10b981' if strategy['win_rate'] >= 50 else '#f59e0b')

            ui.separator().classes('my-1')

            # ── Section: Baselines ──
            ui.label('RISK-FREE BASELINES').classes('bench-header')

            self._bench_row('Buy & Hold', f'{baseline["buy_hold_return"]:+.2f}%',
                            sub=f'{cfg.SYMBOL} over window',
                            color='#94a3b8')
            self._bench_row('Risk-Free Rate', f'{baseline["risk_free_return"]:+.2f}%',
                            sub=f'{baseline["risk_free_annual"]:.1f}% ann. · {baseline["data_years"]:.2f}y',
                            color='#94a3b8')

            ui.separator().classes('my-1')

            # ── Comparison Bars (Strategy vs BH) ──
            ui.label('RETURN COMPARISON').classes('bench-header')

            max_abs = max(abs(strategy['total_return']),
                         abs(baseline['buy_hold_return']),
                         abs(baseline['risk_free_return']),
                         0.01)

            self._comparison_bar('Strategy', strategy['total_return'], max_abs, '#3b82f6')
            self._comparison_bar('Buy & Hold', baseline['buy_hold_return'], max_abs, '#64748b')
            self._comparison_bar('Risk-Free', baseline['risk_free_return'], max_abs, '#94a3b8')

            ui.separator().classes('my-1')

            # ── Verdict ──
            with ui.element('div').classes('bench-verdict'):
                ui.label('VERDICT').classes('bench-verdict-title')
                if alpha > 0 and rf_alpha > 0:
                    verdict = '✅ Strategy beats both baselines'
                    v_color = '#10b981'
                elif alpha > 0:
                    verdict = '⚠️ Beats Buy & Hold, trails risk-free'
                    v_color = '#f59e0b'
                elif rf_alpha > 0:
                    verdict = '⚠️ Beats risk-free, trails Buy & Hold'
                    v_color = '#f59e0b'
                else:
                    verdict = '❌ Underperforms both baselines'
                    v_color = '#ef4444'
                ui.label(verdict).classes('bench-verdict-text').style(f'color:{v_color};')

    # ── Helper: single benchmark metric row ──
    def _bench_row(self, label, value, *, sub=None, color='#e2e8f0'):
        with ui.element('div').classes('bench-metric'):
            ui.label(label).classes('bench-metric-label')
            ui.label(value).classes('bench-metric-value').style(f'color:{color};')
            if sub:
                ui.label(sub).classes('bench-metric-sub')

    # ── Helper: comparison bar ──
    def _comparison_bar(self, label, value, max_abs, color):
        pct = min(abs(value) / max_abs * 100, 100) if max_abs > 0 else 0
        with ui.element('div').classes('w-full'):
            with ui.row().classes('items-center justify-between no-wrap mb-1'):
                ui.label(label).style('font-size:11px;color:#94a3b8;font-family:Inter,sans-serif;')
                val_color = '#10b981' if value >= 0 else '#ef4444'
                ui.label(f'{value:+.2f}%') \
                    .style(f'font-size:12px;font-weight:700;color:{val_color};font-family:JetBrains Mono,monospace;')
            with ui.element('div').classes('bench-bar-track'):
                ui.element('div').classes('bench-bar-fill') \
                    .style(f'width:{pct:.1f}%;background:linear-gradient(90deg,{color},{color}88);')

    # ──────────────────────────────────────────────────────────────────────────
    #  Optimization Panel
    # ──────────────────────────────────────────────────────────────────────────








    # ──────────────────────────────────────────────────────────────────────────
    #  Fine-Tune: Local Search Around Best Result
    # ──────────────────────────────────────────────────────────────────────────




    # ──────────────────────────────────────────────────────────────────────────
    #  Chart Control
    # ──────────────────────────────────────────────────────────────────────────

    async def init_chart(self):
        if self.chart:
            self.chart.init_chart()
        self.log('✅ Chart mounted')

        # Cancel any previously scheduled backtest timer
        if hasattr(self, '_init_timer') and self._init_timer:
            self._init_timer.cancel()
        self._init_timer = ui.timer(1.0, self.run_backtest_simulation, once=True)

    async def run_backtest_simulation(self):
        # ── Guard: prevent concurrent / re-entrant runs ──
        if getattr(self, '_backtest_running', False):
            self._backtest_pending = True          # single dedup'd retry
            # A full load takes ~20s, so this window is wide: clicking
            # "Apply & Preview" during one silently left the previous strategy's
            # chart on screen, which read as the swap being ignored.
            self.log('⏳ A load is already running — queued; chart will refresh when it finishes')
            return False
        self._backtest_running = True
        self._backtest_pending = False
        self._backtest_start_time = time.time()

        # ── Pause live chart updates while the full backtest runs ──
        if hasattr(self, 'update_timer') and self.update_timer:
            try:
                self.update_timer.cancel()
            except Exception as e:
                _report('run_backtest_simulation: could not cancel chart timer', e)
            self.update_timer = None

        try:
            limit = cfg.MAX_FETCH_LIMIT
            strat_name = self.active_strategy_name
            self.log(f'Loading {cfg.SYMBOL} ({cfg.TIMEFRAME}) — strategy: {strat_name}…')

            strategy_json_content = None
            if self.active_strategy_path:
                try:
                    with open(self.active_strategy_path, 'r') as f:
                        strategy_json_content = f.read()
                except Exception as e:
                    self.log(f'Error loading strategy: {e}')

            _strat_json = strategy_json_content

            def _heavy_loader():
                """Run ALL heavy work in a thread to keep the event loop responsive."""
                import numpy as np

                df = self.fetch_and_cache_data(cfg.SYMBOL, cfg.TIMEFRAME, limit)
                if df is None or df.empty:
                    return None, None, None, None, 0, 0
                if len(df) > limit:
                    df = df.tail(limit).copy().reset_index(drop=True)
                config = (
                    self.bot.state.config.copy() if self.bot
                    else cfg.CURRENT_CONFIG.copy()
                )
                df = add_indicators(df, config)
                df = generate_signals(df, config, strategy_json=_strat_json)
                from core.backtester import run_backtest_with_markers, generate_signal_markers
                trade_markers = run_backtest_with_markers(df, config)
                signal_markers = generate_signal_markers(df, warmup=50)

                # ── Build chart_data using vectorized ops (NOT iterrows) ──
                # Resolution-independent: pandas 2+ gives datetime64[ms] here and
                # datetime64[us] via the CSV cache, so a hardcoded //10**9 is off
                # by 10**3–10**6 and lands every candle in 1970.
                from utils import to_epoch_seconds
                timestamps = to_epoch_seconds(df['timestamp'])
                opens  = df['open'].values
                highs  = df['high'].values
                lows   = df['low'].values
                closes = df['close'].values

                chart_data = []
                for i in range(len(df)):
                    o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
                    # Replace NaN/Inf with None
                    if o != o or abs(o) == float('inf'): o = None
                    if h != h or abs(h) == float('inf'): h = None
                    if l != l or abs(l) == float('inf'): l = None
                    if c != c or abs(c) == float('inf'): c = None
                    chart_data.append({
                        'time': int(timestamps.iloc[i]),
                        'open': o, 'high': h, 'low': l, 'close': c,
                    })

                # ── Clean & merge markers ──
                def _clean(m):
                    return {
                        'time': int(m['time']),
                        'position': str(m['position']),
                        'color': str(m['color']),
                        'shape': str(m['shape']),
                        'text': str(m.get('text', '')),
                    }
                cleaned_signals = [_clean(m) for m in (signal_markers or [])]
                cleaned_trades  = [_clean(m) for m in (trade_markers or [])]
                all_markers = sorted(
                    cleaned_signals + cleaned_trades,
                    key=lambda x: x['time'],
                )

                return (df, config, chart_data, all_markers,
                        len(cleaned_signals), len(cleaned_trades))

            self.log(f'Processing data (strategy: {strat_name})…')
            result = await asyncio.to_thread(_heavy_loader)

            # Unpack — _heavy_loader returns a tuple
            if result[0] is None:
                self.log('❌ Failed to fetch data')
                return

            df, bt_config, chart_data, all_markers, n_signals, n_trades = result

            self.log(f'Processing {len(df)} bars…')

            self.chart_markers = all_markers

            # Update KPI
            if hasattr(self, '_kpi_trades'):
                self._kpi_trades.text = str(n_trades)

            if self.chart:
                try:
                    self.chart.set_data(chart_data)
                    if self.chart_markers:
                        self.chart.set_markers(self.chart_markers)
                        self.log(f'✅ {n_signals} signals + {n_trades} trade markers applied')
                except RuntimeError:
                    self.log('⚠️ Chart update skipped (client disconnected)')
                    return

            self.history_data = chart_data
            self.current_price = chart_data[-1]['close'] if chart_data else 0
            self.update_price_label(self.current_price)

            if hasattr(self, 'update_timer') and self.update_timer:
                self.update_timer.cancel()
            self.update_timer = ui.timer(
                cfg.CHART_UPDATE_INTERVAL_SEC, self.update_chart_loop
            )
            self.log('✅ Live chart updates started (trading paused)')

            # ── Compute & display benchmark comparison ──
            try:
                strat_m, base_m = await asyncio.to_thread(
                    self._compute_benchmarks, df, bt_config,
                )
                if strat_m and base_m:
                    self._populate_benchmarks(strat_m, base_m)  # UI update — must run on main loop
                    sortino = strat_m['sortino']
                    sortino_txt = f'{sortino:.2f}' if sortino is not None else 'n/a (no C++ engine)'
                    self.log(
                        f'📊 Benchmarks: Return {strat_m["total_return"]:+.2f}% '
                        f'| α {strat_m["total_return"] - base_m["buy_hold_return"]:+.2f}% '
                        f'| Sortino {sortino_txt}'
                    )
                else:
                    self.log('⚠️ Benchmark computation returned no data')
            except Exception as e:
                self.log(f'⚠️ Benchmark computation skipped: {e}')

            if (
                cfg.AUTO_OPTIMIZE_ON_START
                and self.bot
                and not getattr(self, 'initial_optimization_done', False)
            ):
                self.initial_optimization_done = True
                asyncio.create_task(self.optimization._run_initial_optimization())

        except Exception as e:
            self.log(f'❌ Simulation error: {e}')
            import traceback
            traceback.print_exc()
        finally:
            self._backtest_running = False
            # If another caller requested a run while we were busy, do ONE retry
            if getattr(self, '_backtest_pending', False):
                self._backtest_pending = False
                ui.timer(0.5, self.run_backtest_simulation, once=True)

    async def update_chart_loop(self):
        if getattr(self, 'is_updating_chart', False):
            return
        try:
            self.is_updating_chart = True
            fetch_limit = cfg.CHART_LIVE_FETCH_LIMIT
            latest_df = await asyncio.to_thread(
                fetch_raw_data, cfg.SYMBOL, cfg.TIMEFRAME, fetch_limit
            )

            if latest_df is not None and not latest_df.empty:

                def clean_float(x):
                    if isinstance(x, float):
                        if x != x:
                            return None
                        if x == float('inf') or x == float('-inf'):
                            return None
                    return x

                last_row = latest_df.iloc[-1]
                candle = {
                    'time': int(last_row['timestamp'].timestamp()),
                    'open': clean_float(last_row['open']),
                    'high': clean_float(last_row['high']),
                    'low': clean_float(last_row['low']),
                    'close': clean_float(last_row['close']),
                }
                if self.chart:
                    try:
                        self.chart.update_candle(candle)
                    except RuntimeError:
                        # Expected: client disconnected. This fires on every
                        # poll until the loop is torn down, so it stays silent
                        # by design rather than by omission.
                        pass

                self.update_price_label(last_row['close'])

                config = (
                    self.bot.state.config.copy() if self.bot
                    else cfg.CURRENT_CONFIG.copy()
                )

                _strat_path = self.active_strategy_path
                _strat_json = None
                if _strat_path:
                    try:
                        with open(_strat_path, 'r') as f:
                            _strat_json = f.read()
                    except Exception as e:
                        # Correctness bug when silent: _strat_json stays None, so
                        # generate_signals() falls back to the DEFAULT strategy's
                        # rules and the chart draws markers for a strategy the
                        # user did not select.
                        _report(f'update_chart_loop: cannot read {_strat_path} — '
                                f'markers will use default strategy rules', e)
                        self.log('⚠️ Chart markers using default rules — '
                                 'active strategy file unreadable')

                def _calc_logic(df, cfg_):
                    from core.backtester import run_backtest_with_markers
                    df = add_indicators(df, cfg_)
                    df = generate_signals(df, cfg_, strategy_json=_strat_json)
                    return run_backtest_with_markers(df, cfg_, warmup=50)

                new_chunk_markers = await asyncio.to_thread(
                    _calc_logic, latest_df, config
                )

                cleaned_markers = [m.copy() for m in new_chunk_markers]
                if not hasattr(self, 'chart_markers'):
                    self.chart_markers = []

                if not latest_df.empty:
                    min_ts = int(latest_df['timestamp'].iloc[0].timestamp())
                    max_ts = int(latest_df['timestamp'].iloc[-1].timestamp())

                    kept = [
                        m for m in self.chart_markers
                        if m['time'] < min_ts or m['time'] > max_ts
                    ]
                    kept.extend(cleaned_markers)
                    self.chart_markers = sorted(kept, key=lambda x: x['time'])

                    if self.chart:
                        try:
                            self.chart.set_markers(self.chart_markers)
                        except RuntimeError:
                            # Expected: client disconnected — see above.
                            pass

        except Exception as e:
            print(f'Update error: {e}')
            import traceback
            traceback.print_exc()
        finally:
            self.is_updating_chart = False

    # ──────────────────────────────────────────────────────────────────────────
    #  Utility
    # ──────────────────────────────────────────────────────────────────────────

    def fetch_and_cache_data(self, symbol, timeframe, limit=5000):
        safe_symbol = symbol.replace('/', '_')
        file_path = f'chart_data/{safe_symbol}_{timeframe}.csv'
        existing_df = pd.DataFrame()

        if os.path.exists(file_path):
            try:
                existing_df = pd.read_csv(file_path)
                existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
            except Exception as e:
                # Recoverable (we refetch), but silently losing the cache means
                # every load refetches thousands of bars — a slow dashboard with
                # no visible cause.
                _report(f'fetch_and_cache_data: unreadable cache {file_path}', e)

        if existing_df.empty:
            new_df = fetch_raw_data(symbol, timeframe, limit)
        else:
            fetch_size = min(limit, 1000)
            new_df = fetch_raw_data(symbol, timeframe, fetch_size)

        if new_df is None or new_df.empty:
            return existing_df

        if not existing_df.empty:
            combined = pd.concat([existing_df, new_df])
            combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
            combined = combined.sort_values(by='timestamp').reset_index(drop=True)
            final_df = combined
        else:
            final_df = new_df

        try:
            final_df.to_csv(file_path, index=False)
        except Exception as e:
            _report(f'fetch_and_cache_data: cannot write cache {file_path}', e)

        return final_df

    def log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted = f'[{timestamp}] {msg}'
        # Push directly to the log container (bypasses stdout redirect timing)
        try:
            if hasattr(self, 'log_container') and self.log_container:
                self.log_container.push(formatted)
        except Exception as e:
            _report('log: push to log_container failed', e)
        # Also write to real stdout for terminal visibility
        try:
            if hasattr(self, 'original_stdout'):
                self.original_stdout.write(formatted + '\n')
                self.original_stdout.flush()
            else:
                sys.__stdout__.write(formatted + '\n')
                sys.__stdout__.flush()
        except Exception:
            # Reporter of last resort: stdout itself is gone. Reporting here
            # would recurse into the same failure. Stay silent deliberately.
            pass

    # ──────────────────────────────────────────────────────────────────────────
    #  Strategy Management
    # ──────────────────────────────────────────────────────────────────────────

    def _discover_strategies(self):
        """
        {key: json_path}, delegated to strategies.discover_strategies().

        This used to key on the JSON's lowercased 'strategy_name' ("Regime Rider"
        -> 'regime rider') while STRATEGY_MAP keyed on short identifiers, so two of
        four shipped strategies never resolved. Discovery now lives in exactly one
        place so the two sides cannot drift apart again (ADR-001).
        """
        return strategies_pkg.discover_strategies()

    def _strategy_options(self):
        """{key: display label} for the selector — keys stay canonical."""
        return {
            key: strategies_pkg.display_name(key)
            for key in self._discover_strategies()
        }

    def _get_strategy_info(self, path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return (
                data.get('strategy_name', 'Unknown'),
                data.get('version', '?'),
                data.get('comment', ''),
            )
        except Exception as e:
            # This is where a stray "Active: Unknown v?" in the sidebar comes
            # from — previously with no indication of why.
            _report(f'_get_strategy_info: cannot read {path}', e)
            return ('Unknown', '?', '')

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

        ran = await self.run_backtest_simulation()

        if ran is False:
            # The backtest was deferred, so chart_markers still belong to the
            # PREVIOUS strategy. Showing their counts here labelled them as the
            # newly selected strategy's results.
            self.strat_stats_label.text = 'Stats: pending…'
            return

        if hasattr(self, 'chart_markers') and self.chart_markers:
            # Signal markers have 'Buy'/'Sell' text; trade markers have LONG/SHORT/TP/SL etc.
            n_signals = sum(
                1 for m in self.chart_markers
                if m.get('text', '') in ('Buy', 'Sell')
            )
            n_entries = sum(
                1 for m in self.chart_markers
                if 'LONG' in m.get('text', '') or 'SHORT' in m.get('text', '')
            )
            n_exits = sum(
                1 for m in self.chart_markers
                if any(k in m.get('text', '') for k in ['TP', 'SL', 'TS', 'Exit', 'BE', 'TrendEnd'])
            )
            self.strat_stats_label.text = (
                f'{n_signals} signals · {n_entries} entries · {n_exits} exits'
            )

        self.log(f'Strategy swap complete: {name}')

    # ──────────────────────────────────────────────────────────────────────────
    #  Bot Controls
    # ──────────────────────────────────────────────────────────────────────────

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

    # ──────────────────────────────────────────────────────────────────────────
    #  Status & Price Updates
    # ──────────────────────────────────────────────────────────────────────────

    def update_price_label(self, price):
        self.price_label.text = f'{price:,.2f} USDT'
        if len(self.history_data) > 1:
            prev = self.history_data[-2]['close']
            color = 'text-green-400' if price >= prev else 'text-red-400'
            self.price_label.classes(color, remove='text-green-400 text-red-400')

        if self.bot:
            state = self.bot.state
            bal = state.balance
            start_bal = getattr(cfg, 'START_BALANCE', 100.0)

            # ── Compute unrealized PnL if position is open ──
            unrealized = 0.0
            if state.position != 0 and state.avg_entry > 0 and price > 0:
                if state.position == 1:
                    raw_pnl = (price - state.avg_entry) / state.avg_entry
                else:
                    raw_pnl = (state.avg_entry - price) / state.avg_entry
                lev_pnl = raw_pnl * state.entry_leverage
                # After partial exit, only 50% of balance is at risk
                ratio = 0.5 if state.partial_done else 1.0
                unrealized = bal * ratio * lev_pnl

            equity = bal + unrealized   # dynamic equity
            roi = ((equity - start_bal) / start_bal) * 100
            sign = '+' if roi >= 0 else ''

            # ── Balance label: show equity (confirmed + unrealized) ──
            if state.position != 0:
                self.balance_label.text = (
                    f'${equity:,.2f} ({sign}{roi:.2f}%)  '
                    f'[unrl: {"+" if unrealized >= 0 else ""}${unrealized:,.2f}]'
                )
            else:
                self.balance_label.text = f'${bal:,.2f} ({sign}{roi:.2f}%)'

            roi_color = 'text-green-400' if roi >= 0 else 'text-red-400'
            self.balance_label.classes(
                roi_color, remove='text-green-400 text-red-400 text-gray-300'
            )

            # ── SESSION P&L KPI: equity-based (includes unrealized) ──
            if hasattr(self, '_kpi_pnl'):
                pnl = equity - start_bal
                self._kpi_pnl.text = f'{"+" if pnl >= 0 else ""}${pnl:,.2f}'
                pnl_color = 'text-green-400' if pnl >= 0 else 'text-red-400'
                self._kpi_pnl.classes(
                    pnl_color, remove='text-green-400 text-red-400 text-white'
                )

    def update_status_continuously(self):
        ui.timer(1.0, self._sync_status)

    def _sync_status(self):
        if not self.bot:
            return

        if not self.is_running:
            self.status_label.text = 'STOPPED'
            self.status_label.classes(
                'status-stopped',
                remove='status-running status-paused status-killed',
            )
            return

        if self.bot.state.is_manual_stop:
            self.status_label.text = 'KILLED'
            self.status_label.classes(
                'status-killed',
                remove='status-running status-paused status-stopped',
            )
        elif self.bot.state.is_paused:
            self.status_label.text = 'PAUSED'
            self.status_label.classes(
                'status-paused',
                remove='status-running status-stopped status-killed',
            )
        else:
            self.status_label.text = 'RUNNING'
            self.status_label.classes(
                'status-running',
                remove='status-stopped status-paused status-killed',
            )

    def _sync_timeframe_state(self):
        if not self.bot:
            return
        active_tf = self.bot.state.get_active_timeframe()
        from utils import parse_timeframe_to_minutes, get_next_candle_time

        minutes = parse_timeframe_to_minutes(active_tf)
        if minutes != self.interval_minutes or self.next_candle_time == 0:
            self.interval_minutes = minutes
            self.next_candle_time = get_next_candle_time(self.interval_minutes)

    def _trading_loop(self):
        if not self.bot or not self.is_running:
            return

        active_tf = self.bot.state.get_active_timeframe()
        from utils import parse_timeframe_to_minutes

        active_minutes = parse_timeframe_to_minutes(active_tf)
        if active_minutes != self.interval_minutes:
            self.log(f'🔄 Timeframe changed: {active_tf}')
            self._sync_timeframe_state()

        now = datetime.now().timestamp()
        if now >= self.next_candle_time:
            self.log('⚡ Executing trade job…')
            try:
                self.bot.trade_job()
            except Exception as e:
                self.log(f'❌ Trade job error: {e}')
            self.next_candle_time += self.interval_minutes * 60

        import schedule
        schedule.run_pending()


# ==============================================================================
# 4.  Entry Point
# ==============================================================================

dashboard = TradingDashboard()


@ui.page('/')
async def index():
    dashboard.build_ui()
    ui.timer(0.1, dashboard.on_page_load, once=True)


if __name__ in {'__main__', '__mp_main__'}:
    from core.trader import PaperTrader
    import utils

    print('⚠️ Running in Standalone Mode — attaching PaperTrader…')
    utils.apply_patches()
    bot = PaperTrader()
    dashboard.set_bot(bot)

    ui.run(title='TradeBot Dashboard', dark=True, port=8080)
