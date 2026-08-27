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
                        ui.button('Optimize', on_click=self.run_manual_optimization)
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
            return None, None

        strategy = {
            'total_return': res.get('total_return', 0.0) * 100,  # → percent
            'sortino':       res.get('sortino', 0.0),
            'calmar':        res.get('calmar', 0.0),
            'profit_factor': res.get('profit_factor', 0.0),
            'mdd':           res.get('mdd', 0.0) * 100,          # → percent
            'trades':        res.get('trades', 0),
            'wins':          res.get('wins', 0),
            'win_rate':      (res['wins'] / res['trades'] * 100) if res.get('trades', 0) > 0 else 0.0,
            'balance':       res.get('balance', start_bal),
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

            self._bench_row('Total Return', f'{strategy["total_return"]:+.2f}%',
                            color='#10b981' if strategy['total_return'] >= 0 else '#ef4444')
            self._bench_row('Sortino Ratio', f'{strategy["sortino"]:.3f}',
                            sub='risk-adjusted return', color='#3b82f6')
            self._bench_row('Calmar Ratio', f'{strategy["calmar"]:.3f}',
                            sub='return / max DD', color='#8b5cf6')
            self._bench_row('Profit Factor', f'{strategy["profit_factor"]:.2f}',
                            sub='gross P / gross L', color='#f59e0b')
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

    def _extract_tunable_params(self):
        """
        Parse the active strategy JSON to find tunable indicator parameters.
        Returns list of dicts:
          [{'name': 'rsi_length', 'indicator': 'RSI', 'field': 'length',
            'current': 14, 'default_range': [10,12,14,16,18]}, ...]
        """
        # ── Research-backed ranges for KNN Lorentzian Classification ──
        # Based on jdehorty's original algorithm defaults and empirical
        # sweet spots for crypto 5m/15m timeframes.
        KNOWN_RANGES = {
            # ML Feature indicators (tight around original defaults)
            'rsi_length':      [9, 11, 14, 17, 21],       # F1: RSI (default 14)
            'wt_channel_len':  [8, 9, 10, 11, 14],        # F2: WT channel (default 10)
            'wt_avg_len':      [9, 11, 13, 15],            # F2: WT average (default 11)
            'cci_length':      [14, 17, 20, 23, 26],       # F3: CCI (default 20)
            'adx_length':      [14, 17, 20, 23, 26],       # F4: ADX (default 20)
            'rsi2_length':     [5, 7, 9, 11, 14],          # F5: RSI short (default 9)
            # KNN
            'neighbors':       [6, 8, 10, 12, 16],         # K (default 8, sweet spot 6-16)
            # Kernel (RQ kernel confirmation)
            'kernel_lookback': [4, 6, 8, 10, 12],          # default 8, jdehorty range 3-14
            'kernel_weight':   [3, 5, 8, 10, 12],          # alpha (default 8, range 2-12)
            # EMA filter
            'ema_period':      [50, 80, 120, 160, 200],    # default 80
            # Regime Rider dual-EMA
            'ema_fast_period':  [13, 17, 21, 26, 34],       # Fast EMA (default 21)
            'ema_slow_period':  [34, 44, 55, 70, 89],       # Slow EMA (default 55)
        }
        # Skip these — not worth optimizing (warmup window control)
        SKIP_PARAMS = {'kernel_lookback_mult'}

        strat_path = self.active_strategy_path
        if not strat_path:
            strat_path = os.path.join(BASE_DIR, 'strategies', 'strategies.json')

        try:
            with open(strat_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            # Silently returning [] here renders an empty optimize panel with no
            # explanation — a malformed strategy JSON looked like a broken UI.
            _report(f'_extract_tunable_params: cannot read {strat_path}', e)
            self.log(f'⚠️ Could not read strategy file: {os.path.basename(str(strat_path))}')
            return []

        params = []
        indicators = data.get('definitions', {}).get('indicators', [])

        for ind in indicators:
            ind_name = ind.get('name', '')
            ind_type = ind.get('type', '')
            for key, val in ind.items():
                if key in ('name', 'type', 'source', 'ml_feature'):
                    continue
                # If value is a string param name (not a literal number), it's tunable
                if isinstance(val, str) and not val.replace('.', '', 1).isdigit():
                    if val in SKIP_PARAMS:
                        continue
                    current = cfg.CURRENT_CONFIG.get(val, 14)
                    # Use research-backed range if known, else generic fallback
                    if val in KNOWN_RANGES:
                        rng = KNOWN_RANGES[val]
                    elif isinstance(current, float):
                        step = max(1.0, round(current * 0.15, 1))
                        rng = [round(current - 2 * step, 1), round(current - step, 1),
                               round(current, 1),
                               round(current + step, 1), round(current + 2 * step, 1)]
                        rng = [max(1.0, v) for v in rng]
                    else:
                        current = int(current)
                        step = max(1, current // 5)
                        rng = list(range(max(1, current - 2 * step),
                                         current + 2 * step + 1, step))
                    params.append({
                        'name': val,
                        'indicator': ind_type.upper() if ind_type else ind_name,
                        'field': key,
                        'current': current,
                        'default_range': sorted(set(rng)),
                    })

        # KNN hyperparameter (not in indicator JSON, must be added explicitly)
        params.append({
            'name': 'neighbors',
            'indicator': 'KNN',
            'field': 'K neighbors',
            'current': cfg.CURRENT_CONFIG.get('neighbors', 8),
            'default_range': KNOWN_RANGES.get('neighbors', [6, 8, 10, 12, 16]),
        })

        # Add filter / risk params
        filter_params = [
            ('adx_threshold', 'ADX Filter', 'threshold', [15, 20, 25, 30]),
            ('chop_threshold', 'Choppiness Filter', 'threshold', [38.0, 45.0, 53.0, 60.0]),
            ('use_ema_filter', 'EMA Filter', 'toggle', [0.0, 1.0]),
            ('use_adx_filter', 'ADX Filter', 'toggle', [0.0, 1.0]),
            ('sl_multiplier', 'Trailing Stop', 'ATR mult', [4.0, 5.0, 6.0, 7.0, 8.0]),
            ('rsi_momentum_gate', 'RSI Momentum', 'long gate', [40, 44, 48, 50]),
            ('rsi_counter_gate', 'RSI Momentum', 'short gate', [50, 52, 56, 60]),
        ]
        for pname, ind_label, field, default_rng in filter_params:
            current = cfg.CURRENT_CONFIG.get(pname, default_rng[0])
            params.append({
                'name': pname,
                'indicator': ind_label,
                'field': field,
                'current': current,
                'default_range': default_rng,
            })

        # Leverage (always available)
        lev_range = getattr(cfg, 'LEVERAGE_TEST_RANGE', [1, 2, 3, 4, 5, 6, 7])
        params.append({
            'name': 'leverage',
            'indicator': 'Risk',
            'field': 'leverage',
            'current': cfg.CURRENT_CONFIG.get('leverage', 3),
            'default_range': lev_range,
        })

        # De-duplicate by param name
        seen = set()
        unique = []
        for p in params:
            if p['name'] not in seen:
                seen.add(p['name'])
                unique.append(p)

        return unique

    def open_optimization_dialog(self):
        """Open the optimization configuration dialog."""
        tunable = self._extract_tunable_params()
        if not tunable:
            ui.notify('No tunable parameters found in strategy', type='warning')
            return

        self._optim_checkboxes = {}
        self._optim_range_inputs = {}
        self._optim_dialog = None

        with ui.dialog().classes('optim-dialog') as dialog, \
             ui.card().classes('optim-card'):

            self._optim_dialog = dialog

            # ── Header ──
            with ui.row().classes('w-full items-center no-wrap px-6 pt-4 pb-2'):
                ui.icon('tune', size='22px').classes('text-blue-400')
                ui.label('Strategy Optimization').classes(
                    'text-base font-bold text-white tracking-wide')
                ui.space()
                ui.button(icon='close', on_click=dialog.close) \
                    .props('flat dense round size=sm').classes('text-gray-500')

            ui.separator()

            # ── Scrollable body ──
            with ui.element('div').classes('optim-card-inner'):

                ui.label('Select parameters to optimize and set their search ranges.') \
                    .classes('text-xs text-gray-500 mb-2')

                # ── Indicator Parameters ──
                ui.label('INDICATOR PARAMETERS').classes('optim-section-title')

                for p in tunable:
                    if p['name'] in ('leverage', 'adx_threshold', 'chop_threshold',
                                     'use_ema_filter', 'use_adx_filter', 'sl_multiplier'):
                        continue  # shown in filter section
                    self._build_param_row(p)

                # ── Filter & Risk Parameters ──
                ui.label('FILTER & RISK PARAMETERS').classes('optim-section-title')

                for p in tunable:
                    if p['name'] in ('leverage', 'adx_threshold', 'chop_threshold',
                                     'use_ema_filter', 'use_adx_filter', 'sl_multiplier'):
                        self._build_param_row(p)

                # ── Leverage ──
                ui.label('LEVERAGE').classes('optim-section-title')
                for p in tunable:
                    if p['name'] == 'leverage':
                        self._build_param_row(p)

                # ── Optimizer Settings ──
                ui.separator().classes('my-2')
                ui.label('OPTIMIZER SETTINGS').classes('optim-section-title')

                with ui.row().classes('w-full gap-4 items-center'):
                    self._optim_method = ui.toggle(
                        {0: 'Grid Search', 1: 'PSO (Swarm)'},
                        value=1 if getattr(cfg, 'USE_PSO', False) else 0,
                    ).props('dense no-caps').classes('text-xs')

                # ── Progress container (hidden initially) ──
                self._optim_progress_container = ui.column().classes('w-full gap-2 mt-3')
                self._optim_progress_container.set_visibility(False)

            # ── Footer buttons ──
            ui.separator()
            with ui.row().classes('w-full items-center justify-end gap-3 px-6 py-3'):
                ui.button('Cancel', on_click=dialog.close) \
                    .props('flat').classes('btn-modern btn-ghost')
                ui.button('Run Optimization', on_click=self._run_optimization_from_panel) \
                    .props('unelevated icon=rocket_launch') \
                    .classes('btn-modern btn-primary text-white px-6')

        dialog.open()

    def _build_param_row(self, param):
        """Build a single parameter row with checkbox + range input."""
        with ui.element('div').classes('optim-param-row mb-2'):
            with ui.row().classes('w-full items-center no-wrap gap-3'):
                cb = ui.checkbox(param['indicator'], value=False).props('dense')
                cb.classes('text-sm')
                self._optim_checkboxes[param['name']] = cb

                ui.space()

                ui.label(f"Current: {param['current']}") \
                    .classes('optim-param-sub')

            # Range input
            range_str = ', '.join(str(v) for v in param['default_range'])
            inp = ui.input(
                label=f"{param['name']} values",
                value=range_str,
            ).props('dense outlined dark').classes('w-full mt-1 optim-range-input text-xs')
            self._optim_range_inputs[param['name']] = inp

    async def _run_optimization_from_panel(self):
        """Collect checked params, build ranges, and run optimization."""
        # 1. Collect checked parameters
        selected_params = {}
        for pname, cb in self._optim_checkboxes.items():
            if cb.value:
                raw = self._optim_range_inputs[pname].value
                try:
                    values = [float(v.strip()) for v in raw.split(',') if v.strip()]
                except ValueError:
                    ui.notify(f'Invalid range for {pname}', type='negative')
                    return
                if not values:
                    ui.notify(f'Empty range for {pname}', type='negative')
                    return
                selected_params[pname] = values

        if not selected_params:
            ui.notify('Select at least one parameter to optimize', type='warning')
            return

        use_pso = self._optim_method.value == 1

        # 2. Show progress
        self._optim_progress_container.set_visibility(True)
        with self._optim_progress_container:
            self._optim_progress_container.clear()
            with ui.element('div').classes('optim-progress'):
                ui.spinner('dots', size='lg', color='blue')
                self._optim_status_label = ui.label('Preparing optimization…') \
                    .classes('text-sm text-gray-300 mt-2')
                self._optim_detail_label = ui.label('') \
                    .classes('text-xs text-gray-500 mt-1 font-mono')

        self.log(f'🚀 Optimization started: {len(selected_params)} params ({"PSO" if use_pso else "Grid"}) — 4d optimize + 3d verify')

        # 3. Run optimization in background thread (chart keeps updating)
        try:
            result = await asyncio.to_thread(
                self._execute_panel_optimization, selected_params, use_pso
            )
            if result:
                self._show_optimization_results(result, selected_params)
            else:
                self._optim_status_label.text = '❌ No valid results found — try wider search ranges'
                self.log(f'❌ Optimization returned no valid results ({len(selected_params)} params)')
        except Exception as e:
            self._optim_status_label.text = f'❌ Error: {e}'
            self.log(f'❌ Optimization error: {e}')
            import traceback
            traceback.print_exc()

    def _execute_panel_optimization(self, selected_params, use_pso):
        """
        Run the actual optimization (called in a background thread).
        Uses a 7-day window: 4 days in-sample for optimization,
        3 days out-of-sample for verification.
        Returns the best result dict (with 'oos' verification metrics) or None.
        """
        try:
            import cpp_engine
        except ImportError:
            print('[Optimization] C++ engine not available')
            return None

        # Load strategy JSON
        strat_path = self.active_strategy_path
        if not strat_path:
            strat_path = os.path.join(BASE_DIR, 'strategies', 'strategies.json')

        strategy_json_content = '{}'
        if os.path.exists(strat_path):
            with open(strat_path, 'r') as f:
                strategy_json_content = f.read()

        # ── Fetch 7 days of data ──
        # Calculate bars per day from timeframe (e.g. 5m → 288, 15m → 96, 1h → 24)
        tf = cfg.TIMEFRAME
        if 'm' in tf:
            bars_per_day = (24 * 60) // int(tf.replace('m', ''))
        elif 'h' in tf:
            bars_per_day = 24 // int(tf.replace('h', ''))
        else:
            bars_per_day = 288  # fallback to 5m

        total_days = 7
        optim_days = 4
        verify_days = 3
        total_bars = bars_per_day * total_days
        optim_bars = bars_per_day * optim_days
        verify_bars = bars_per_day * verify_days

        df_raw = fetch_raw_data(cfg.SYMBOL, cfg.TIMEFRAME, total_bars)
        if df_raw is None or df_raw.empty:
            print('[Optimization] Failed to fetch data — check API keys and connection')
            return None

        # Take exactly what we got (may be slightly less than requested)
        df_all = df_raw.copy().reset_index(drop=True)
        actual_total = len(df_all)
        # Proportional split: 4/7 optimize, 3/7 verify
        actual_optim = int(actual_total * optim_days / total_days)
        actual_verify = actual_total - actual_optim

        df_optim = df_all.iloc[:actual_optim].copy().reset_index(drop=True)
        df_verify = df_all.iloc[actual_optim:].copy().reset_index(drop=True)

        print(f'[Optimization] Fetched {actual_total} bars of {cfg.SYMBOL} {cfg.TIMEFRAME}')
        print(f'[Optimization] In-sample:  {len(df_optim)} bars ({optim_days}d)  '
              f'{df_optim["timestamp"].iloc[0]} → {df_optim["timestamp"].iloc[-1]}')
        print(f'[Optimization] Out-of-sample: {len(df_verify)} bars ({verify_days}d)  '
              f'{df_verify["timestamp"].iloc[0]} → {df_verify["timestamp"].iloc[-1]}')

        local_config = cfg.CURRENT_CONFIG.copy()

        # Known indicator param names
        from core.optimizer import get_indicator_params_from_json
        ind_param_names = get_indicator_params_from_json()

        # Split selected into indicator vs filter
        ind_names, ind_values = [], []
        filt_names, filt_values = [], []

        for pname, values in selected_params.items():
            if pname in ind_param_names:
                ind_names.append(pname)
                ind_values.append([float(v) for v in values])
            else:
                filt_names.append(pname)
                filt_values.append([float(v) for v in values])

        # If no indicator params selected, need at least one placeholder
        if not ind_names:
            rsi_val = float(local_config.get('rsi_length', 14))
            ind_names.append('rsi_length')
            ind_values.append([rsi_val])

        total_combos = 1
        for v in ind_values + filt_values:
            total_combos *= len(v)
        print(f'[Optimization] {len(ind_names)} ind + {len(filt_names)} filt params, {total_combos} combinations')

        # ── Run optimization on IN-SAMPLE (4 days) ──
        if use_pso:
            all_names = ind_names + filt_names
            all_mins = [min(v) for v in ind_values + filt_values]
            all_maxs = [max(v) for v in ind_values + filt_values]
            all_defaults = [float(local_config.get(nm, (mn + mx) / 2))
                            for nm, mn, mx in zip(all_names, all_mins, all_maxs)]

            # ── Inject ALL config values not already selected as fixed-point
            #    dims (min==max==current) so the C++ param resolver always
            #    finds them.  Without this, unselected params resolve to 0
            #    inside the PSO evaluator (e.g. neighbors=0 → KNN skipped,
            #    kernel_lookback_mult=0 → broken kernel). ──
            selected_set = set(all_names)
            fixed_config = local_config.copy()
            fixed_config['kernel_lookback_mult'] = float(
                getattr(cfg, 'KERNEL_LOOKBACK_MULT', 3))
            for pname, pval in fixed_config.items():
                if pname in selected_set:
                    continue
                if not isinstance(pval, (int, float)):
                    continue
                val = float(pval)
                all_names.append(pname)
                all_mins.append(val)
                all_maxs.append(val)    # min == max → fixed
                all_defaults.append(val)

            n_dims = len(all_names)
            n_free = len(selected_set)  # Only count actually-optimized dims

            base_swarm = int(getattr(cfg, 'PSO_SWARM_SIZE', 50))
            base_iters = int(getattr(cfg, 'PSO_MAX_ITERATIONS', 30))
            swarm_size = max(base_swarm, n_free * 20)
            max_iters  = max(base_iters, n_free * 6)
            print(f'[PSO] dims={n_dims} ({n_free} free + {n_dims - n_free} fixed), '
                  f'swarm={swarm_size}, iters={max_iters}, evals={swarm_size * max_iters}')
            for i, nm in enumerate(all_names):
                tag = '' if nm in selected_set else ' [FIXED]'
                print(f'  [{nm}] {all_mins[i]:.4f} .. {all_maxs[i]:.4f}  (default={all_defaults[i]:.4f}){tag}')

            res_list = cpp_engine.optimize_pso(
                df_optim['open'].values.astype(float),
                df_optim['high'].values.astype(float),
                df_optim['low'].values.astype(float),
                df_optim['close'].values.astype(float),
                all_names, all_mins, all_maxs,
                all_defaults,
                strategy_json_content,
                int(cfg.OPTIMIZER_MIN_TRADES),
                int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                float(cfg.OPTIMIZER_MAX_MDD),
                float(getattr(cfg, 'START_BALANCE', 100.0)),
                float(getattr(cfg, 'FEE_RATE', 0.001)),
                float(local_config.get('tp_ratio', 0.99)),
                float(local_config.get('sl_ratio', 0.03)),
                int(local_config.get('kernel_lookback', 9)),
                float(local_config.get('kernel_weight', 8.0)),
                int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
                swarm_size,
                max_iters,
            )
            print(f'[PSO] Returned {len(res_list)} results')

            if not res_list:
                print('[PSO] Retrying with relaxed constraints (min_trades=3, max_mdd=0.6)…')
                res_list = cpp_engine.optimize_pso(
                    df_optim['open'].values.astype(float),
                    df_optim['high'].values.astype(float),
                    df_optim['low'].values.astype(float),
                    df_optim['close'].values.astype(float),
                    all_names, all_mins, all_maxs,
                    all_defaults,
                    strategy_json_content,
                    3,
                    int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                    0.6,
                    float(getattr(cfg, 'START_BALANCE', 100.0)),
                    float(getattr(cfg, 'FEE_RATE', 0.001)),
                    float(local_config.get('tp_ratio', 0.99)),
                    float(local_config.get('sl_ratio', 0.03)),
                    int(local_config.get('kernel_lookback', 9)),
                    float(local_config.get('kernel_weight', 8.0)),
                    int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
                    swarm_size,
                    max_iters * 2,
                )
                print(f'[PSO] Relaxed retry returned {len(res_list)} results')
        else:
            res_list = cpp_engine.optimize_generic(
                df_optim['open'].values.astype(float),
                df_optim['high'].values.astype(float),
                df_optim['low'].values.astype(float),
                df_optim['close'].values.astype(float),
                ind_names, ind_values,
                filt_names, filt_values,
                strategy_json_content,
                int(cfg.OPTIMIZER_MIN_TRADES),
                int(getattr(cfg, 'OPTIMIZER_MAX_TRADES', 2500)),
                float(cfg.OPTIMIZER_MAX_MDD),
                float(getattr(cfg, 'START_BALANCE', 100.0)),
                float(getattr(cfg, 'FEE_RATE', 0.001)),
                float(local_config.get('tp_ratio', 0.99)),
                float(local_config.get('sl_ratio', 0.03)),
                int(local_config.get('kernel_lookback', 9)),
                float(local_config.get('kernel_weight', 8.0)),
                int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
            )

        if not res_list:
            print('[Optimization] No valid results on in-sample data')
            return None

        # Pick best by score (in-sample)
        best = max(res_list, key=lambda r: r.get('best_score', -999))
        best_params = best.get('best_params', {})
        print(f'[Optimization] Best in-sample: score={best.get("best_score", 0):.4f}, '
              f'trades={best.get("trades", 0)}, bal=${best.get("balance", 0):.2f}')

        # ── Verification on OUT-OF-SAMPLE (3 days) ──
        if len(df_verify) >= 200:
            print(f'[Verification] Running out-of-sample backtest on {len(df_verify)} bars…')
            # Run a single-point PSO evaluation with the best params on OOS data
            oos_names = list(best_params.keys())
            oos_vals = [float(best_params[k]) for k in oos_names]

            oos_list = cpp_engine.optimize_pso(
                df_verify['open'].values.astype(float),
                df_verify['high'].values.astype(float),
                df_verify['low'].values.astype(float),
                df_verify['close'].values.astype(float),
                oos_names,
                oos_vals,     # min = exact value
                oos_vals,     # max = exact value (fixed point)
                oos_vals,     # defaults = same
                strategy_json_content,
                1, 99999, 0.99,   # very permissive constraints for verification
                float(getattr(cfg, 'START_BALANCE', 100.0)),
                float(getattr(cfg, 'FEE_RATE', 0.001)),
                float(best_params.get('tp_ratio', local_config.get('tp_ratio', 0.99))),
                float(best_params.get('sl_ratio', local_config.get('sl_ratio', 0.03))),
                int(best_params.get('kernel_lookback', local_config.get('kernel_lookback', 9))),
                float(best_params.get('kernel_weight', local_config.get('kernel_weight', 8.0))),
                int(getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)),
                1, 1,  # single particle, single iteration
            )

            if oos_list:
                oos = oos_list[0]
                best['oos'] = {
                    'balance': oos.get('balance', 0),
                    'trades': oos.get('trades', 0),
                    'wins': oos.get('wins', 0),
                    'mdd': oos.get('mdd', 0),
                    'sortino': oos.get('sortino', 0),
                    'total_return': oos.get('total_return', 0),
                    'calmar': oos.get('calmar', 0),
                    'profit_factor': oos.get('profit_factor', 0),
                }
                oos_ret = oos.get('total_return', 0) * 100
                print(f'[Verification] OOS: bal=${oos["balance"]:.2f}, '
                      f'ret={oos_ret:+.1f}%, trades={oos["trades"]}, '
                      f'sortino={oos.get("sortino", 0):.3f}, mdd={oos.get("mdd", 0)*100:.1f}%')
            else:
                print('[Verification] OOS backtest returned no results (no trades in verification period)')
                best['oos'] = None
        else:
            print(f'[Verification] Skipped — only {len(df_verify)} OOS bars (need ≥200)')
            best['oos'] = None

        # Store date ranges for display
        best['_is_range'] = f'{df_optim["timestamp"].iloc[0].strftime("%m/%d")} – {df_optim["timestamp"].iloc[-1].strftime("%m/%d")}'
        best['_oos_range'] = f'{df_verify["timestamp"].iloc[0].strftime("%m/%d")} – {df_verify["timestamp"].iloc[-1].strftime("%m/%d")}' if len(df_verify) > 0 else ''
        best['_is_bars'] = len(df_optim)
        best['_oos_bars'] = len(df_verify)

        return best

    def _show_optimization_results(self, result, selected_params):
        """Display optimization results with in-sample and out-of-sample sections."""
        self._optim_progress_container.clear()
        self._optim_progress_container.set_visibility(True)

        best_params = result.get('best_params', {})
        balance = result.get('balance', 0)
        trades = result.get('trades', 0)
        wins = result.get('wins', 0)
        mdd = result.get('mdd', 0)
        sortino = result.get('sortino', 0)
        total_ret = result.get('total_return', 0) * 100
        wr = (wins / trades * 100) if trades > 0 else 0

        oos = result.get('oos')
        is_range = result.get('_is_range', '')
        oos_range = result.get('_oos_range', '')
        is_bars = result.get('_is_bars', 0)
        oos_bars = result.get('_oos_bars', 0)

        # Log summary
        log_msg = (f'✅ IS ({is_range}): Bal ${balance:.2f} | Ret {total_ret:+.1f}% | '
                   f'Sortino {sortino:.2f} | WR {wr:.0f}% | MDD {mdd*100:.1f}%')
        if oos:
            oos_ret = oos['total_return'] * 100
            oos_wr = (oos['wins'] / oos['trades'] * 100) if oos['trades'] > 0 else 0
            log_msg += (f'  ·  OOS ({oos_range}): Bal ${oos["balance"]:.2f} | '
                        f'Ret {oos_ret:+.1f}% | Sortino {oos["sortino"]:.2f} | '
                        f'WR {oos_wr:.0f}% | MDD {oos["mdd"]*100:.1f}%')
        self.log(log_msg)

        with self._optim_progress_container:
            # ── In-Sample Results ──
            with ui.element('div').classes('optim-result-card'):
                with ui.row().classes('w-full items-center gap-2'):
                    ui.icon('model_training', size='16px').classes('text-blue-400')
                    ui.label('IN-SAMPLE (Optimization)').classes('optim-section-title')
                    ui.space()
                    ui.label(f'{is_range}  ·  {is_bars} bars').style(
                        'font-size:10px;color:#64748b;font-family:JetBrains Mono,monospace;')

                with ui.row().classes('w-full gap-4 flex-wrap'):
                    self._optim_result_chip('Balance', f'${balance:.2f}', '#10b981')
                    self._optim_result_chip('Return', f'{total_ret:+.1f}%',
                                           '#10b981' if total_ret >= 0 else '#ef4444')
                    self._optim_result_chip('Sortino', f'{sortino:.3f}', '#3b82f6')
                    self._optim_result_chip('Win Rate', f'{wr:.0f}%', '#f59e0b')
                    self._optim_result_chip('MDD', f'{mdd*100:.1f}%', '#ef4444')
                    self._optim_result_chip('Trades', str(trades), '#8b5cf6')

            # ── Out-of-Sample Results ──
            with ui.element('div').classes('optim-result-card').style('margin-top:8px;'):
                with ui.row().classes('w-full items-center gap-2'):
                    ui.icon('verified', size='16px').classes('text-amber-400')
                    ui.label('OUT-OF-SAMPLE (Verification)').classes('optim-section-title')
                    ui.space()
                    ui.label(f'{oos_range}  ·  {oos_bars} bars').style(
                        'font-size:10px;color:#64748b;font-family:JetBrains Mono,monospace;')

                if oos and oos.get('trades', 0) > 0:
                    oos_ret = oos['total_return'] * 100
                    oos_wr = (oos['wins'] / oos['trades'] * 100) if oos['trades'] > 0 else 0
                    with ui.row().classes('w-full gap-4 flex-wrap'):
                        self._optim_result_chip('Balance', f'${oos["balance"]:.2f}',
                                               '#10b981' if oos['total_return'] >= 0 else '#ef4444')
                        self._optim_result_chip('Return', f'{oos_ret:+.1f}%',
                                               '#10b981' if oos_ret >= 0 else '#ef4444')
                        self._optim_result_chip('Sortino', f'{oos["sortino"]:.3f}', '#3b82f6')
                        self._optim_result_chip('Win Rate', f'{oos_wr:.0f}%', '#f59e0b')
                        self._optim_result_chip('MDD', f'{oos["mdd"]*100:.1f}%', '#ef4444')
                        self._optim_result_chip('Trades', str(oos['trades']), '#8b5cf6')

                    # Overfitting check
                    is_sortino = sortino
                    oos_sortino = oos['sortino']
                    if is_sortino > 0 and oos_sortino > 0:
                        ratio = oos_sortino / is_sortino
                        if ratio >= 0.5:
                            ui.label(f'✅ OOS/IS Sortino ratio: {ratio:.2f} — strategy generalizes well') \
                                .style('font-size:11px;color:#10b981;margin-top:4px;')
                        else:
                            ui.label(f'⚠️ OOS/IS Sortino ratio: {ratio:.2f} — possible overfitting') \
                                .style('font-size:11px;color:#f59e0b;margin-top:4px;')
                    elif oos_ret < 0 and total_ret > 0:
                        ui.label('⚠️ In-sample profitable but OOS negative — likely overfit') \
                            .style('font-size:11px;color:#ef4444;margin-top:4px;')
                else:
                    ui.label('No trades generated in the verification period') \
                        .style('font-size:11px;color:#64748b;font-style:italic;margin-top:4px;')

            ui.separator().classes('my-2')

            # ── Optimized Values ──
            with ui.element('div').classes('optim-result-card').style('margin-top:4px;'):
                ui.label('OPTIMIZED VALUES').classes('optim-section-title')
                for pname in selected_params:
                    if pname in best_params:
                        old_val = cfg.CURRENT_CONFIG.get(pname, '?')
                        new_val = best_params[pname]
                        if isinstance(new_val, float) and new_val == int(new_val):
                            new_val = int(new_val)
                        color = '#10b981' if new_val != old_val else '#94a3b8'
                        with ui.row().classes('items-center gap-2'):
                            ui.label(pname).classes('text-xs font-mono text-gray-400')
                            ui.label(f'{old_val}').classes('text-xs font-mono text-gray-600 line-through')
                            ui.icon('arrow_forward', size='12px').classes('text-gray-600')
                            ui.label(f'{new_val}').classes('text-xs font-mono font-bold') \
                                .style(f'color:{color};')

            # ── Save Options ──
            ui.separator().classes('my-3')
            ui.label('SAVE OPTIONS').classes('optim-section-title')

            with ui.row().classes('w-full gap-3'):
                ui.button('Apply to Current',
                          on_click=lambda: self._apply_optimization_result(best_params, overwrite=True)) \
                    .props('unelevated icon=save') \
                    .classes('btn-modern btn-success text-white px-4')

                self._new_name_input = ui.input(
                    label='New strategy name',
                    value=f'{self.active_strategy_name}_optimized',
                ).props('dense outlined dark').classes('flex-1 optim-range-input')

                ui.button('Save as New',
                          on_click=lambda: self._apply_optimization_result(best_params, overwrite=False)) \
                    .props('unelevated icon=add_circle') \
                    .classes('btn-modern btn-purple text-white px-4')

            # ── Fine-Tune ──
            ui.separator().classes('my-2')
            with ui.row().classes('w-full items-center gap-3'):
                ui.button('Fine-Tune Best Result',
                          on_click=lambda: self._run_fine_tune(best_params, selected_params)) \
                    .props('unelevated icon=precision_manufacturing') \
                    .classes('btn-modern text-white px-4') \
                    .style('background:linear-gradient(135deg,#6366f1,#8b5cf6);')

    def _optim_result_chip(self, label, value, color):
        """Small result display chip."""
        with ui.element('div').style(
            f'background:rgba(255,255,255,0.04);border-radius:8px;'
            f'padding:8px 12px;min-width:90px;'):
            ui.label(label).style('font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;')
            ui.label(value).style(f'font-size:15px;font-weight:700;color:{color};font-family:JetBrains Mono,monospace;')

    # ──────────────────────────────────────────────────────────────────────────
    #  Fine-Tune: Local Search Around Best Result
    # ──────────────────────────────────────────────────────────────────────────

    async def _run_fine_tune(self, best_params, selected_params):
        """Re-run PSO with narrow ±ranges around the best result to squeeze out more performance."""
        # Build tight ranges: ±1-2 steps around each optimized value
        fine_params = {}
        for pname in selected_params:
            if pname not in best_params:
                continue
            best_val = float(best_params[pname])
            orig_range = selected_params[pname]
            orig_range_sorted = sorted(orig_range)

            # Compute step from the original range
            if len(orig_range_sorted) >= 2:
                steps = [orig_range_sorted[i+1] - orig_range_sorted[i]
                         for i in range(len(orig_range_sorted) - 1)]
                step = min(steps) if steps else 1.0
            else:
                step = max(1.0, abs(best_val) * 0.05)

            # Use a fractional step for fine-tuning (half the original step)
            fine_step = step / 2.0 if step > 1.0 else step
            if fine_step < 0.5:
                fine_step = 0.5

            # Generate ±3 fine points around best
            fine_vals = set()
            for offset in [-3, -2, -1, 0, 1, 2, 3]:
                candidate = best_val + offset * fine_step
                # Keep within original bounds
                if candidate >= orig_range_sorted[0] - step and candidate <= orig_range_sorted[-1] + step:
                    if candidate > 0 or pname in ('use_ema_filter', 'use_adx_filter'):
                        fine_vals.add(round(candidate, 4))

            # Integer params stay integer
            if all(v == int(v) for v in orig_range):
                fine_vals = {float(int(v)) for v in fine_vals if v >= 1}

            fine_params[pname] = sorted(fine_vals) if fine_vals else [best_val]

        if not fine_params:
            ui.notify('No parameters to fine-tune', type='warning')
            return

        # Show progress
        self._optim_progress_container.clear()
        self._optim_progress_container.set_visibility(True)
        with self._optim_progress_container:
            with ui.element('div').classes('optim-progress'):
                ui.spinner('dots', size='lg', color='purple')
                self._optim_status_label = ui.label('Fine-tuning around best result…') \
                    .classes('text-sm text-gray-300 mt-2')
                # Show fine-tune ranges
                for pname, vals in fine_params.items():
                    ui.label(f'  {pname}: {vals}') \
                        .classes('text-xs text-gray-500 font-mono')

        self.log(f'🔬 Fine-tuning {len(fine_params)} params around optimized values…')

        try:
            result = await asyncio.to_thread(
                self._execute_panel_optimization, fine_params, True  # always PSO for fine-tune
            )
            if result:
                # Compare with previous best
                prev_score = max(best_params.get('_prev_score', -999),
                                 sum(best_params.values()) * 0)  # just use 0 as fallback
                new_score = result.get('best_score', -999)
                self.log(f'🔬 Fine-tune complete: score={new_score:.4f}')
                self._show_optimization_results(result, fine_params)
            else:
                self._optim_status_label.text = '❌ Fine-tune found no valid results'
                self.log('❌ Fine-tune returned no valid results')
        except Exception as e:
            self._optim_status_label.text = f'❌ Error: {e}'
            self.log(f'❌ Fine-tune error: {e}')
            import traceback
            traceback.print_exc()

    async def _apply_optimization_result(self, best_params, overwrite=True):
        """Apply optimized params: either overwrite current strategy or save as new JSON."""
        if overwrite:
            # Update CURRENT_CONFIG in-memory
            for k, v in best_params.items():
                if k in cfg.CURRENT_CONFIG:
                    if isinstance(cfg.CURRENT_CONFIG[k], int) and isinstance(v, float):
                        v = int(v)
                    cfg.CURRENT_CONFIG[k] = v

            # [Session-Only] Optimized values stay in-memory only.
            # The strategy JSON file on disk is NOT modified.

            # Update bot if attached
            if self.bot:
                with self.bot.lock:
                    self.bot.state.config.update(cfg.CURRENT_CONFIG)
                    self.bot.state.update_config(self.bot.state.config)

            ui.notify('✅ Applied to current strategy', type='positive', position='bottom-right')
            self.log(f'✅ Optimized params applied to {self.active_strategy_name}')

        else:
            # Save as new strategy JSON in repository
            new_name = self._new_name_input.value.strip()
            if not new_name:
                ui.notify('Enter a strategy name', type='warning')
                return

            repo_dir = os.path.join(BASE_DIR, 'strategies', 'repository')
            os.makedirs(repo_dir, exist_ok=True)
            safe_name = new_name.replace(' ', '_').lower()
            new_path = os.path.join(repo_dir, f'{safe_name}.json')

            # Load current strategy as base
            strat_path = self.active_strategy_path or \
                os.path.join(BASE_DIR, 'strategies', 'strategies.json')
            try:
                with open(strat_path, 'r') as f:
                    data = json.load(f)
            except Exception:
                data = {}

            # Update strategy metadata
            data['strategy_name'] = new_name
            data['version'] = '1.0'
            data['comment'] = f'Optimized from {self.active_strategy_name}'

            # Embed optimized config values so the strategy is self-contained
            opt_config = cfg.CURRENT_CONFIG.copy()
            for k, v in best_params.items():
                if isinstance(v, float) and v == int(v):
                    v = int(v)
                opt_config[k] = v
            data['optimized_config'] = opt_config

            # Write new file
            with open(new_path, 'w') as f:
                json.dump(data, f, indent=4)

            # Also write a config snapshot alongside
            self._update_strategy_json(new_path, best_params)

            ui.notify(f'✅ Saved as "{new_name}"', type='positive', position='bottom-right')
            self.log(f'✅ New strategy saved: {new_path}')

            # Refresh strategy list in sidebar
            self.available_strategies = self._discover_strategies()
            self.strategy_select.options = list(self.available_strategies.keys())
            self.strategy_select.update()

        # Refresh chart
        if self._optim_dialog:
            self._optim_dialog.close()
        await self.run_backtest_simulation()

    def _update_strategy_json(self, path, best_params):
        """
        Update indicator lengths and config params in a strategy JSON file.
        Maps param names back to indicator fields.
        """
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            # Returning silently meant "Apply optimized params" reported success
            # while writing nothing at all.
            _report(f'_update_strategy_json: cannot read {path}', e)
            self.log(f'❌ Could not apply params — unreadable strategy file: {path}')
            return

        # Update indicator params (string-referenced lengths)
        indicators = data.get('definitions', {}).get('indicators', [])
        for ind in indicators:
            for key, val in list(ind.items()):
                if key in ('name', 'type', 'source', 'ml_feature'):
                    continue
                if isinstance(val, str) and val in best_params:
                    # The JSON stores param NAME as value (e.g. "rsi_length").
                    # We don't change the JSON reference — the actual value lives
                    # in CURRENT_CONFIG which was already updated.
                    pass

        # Save back (metadata may have been updated)
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f'Error saving strategy JSON: {e}')

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
            return
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
                timestamps = df['timestamp'].astype('int64') // 10**9  # ns → s
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
                    self.log(
                        f'📊 Benchmarks: Return {strat_m["total_return"]:+.2f}% '
                        f'| α {strat_m["total_return"] - base_m["buy_hold_return"]:+.2f}% '
                        f'| Sortino {strat_m["sortino"]:.2f}'
                    )
                else:
                    self.log('⚠️ Benchmark computation returned no data (cpp_engine not available?)')
            except Exception as e:
                self.log(f'⚠️ Benchmark computation skipped: {e}')

            if (
                cfg.AUTO_OPTIMIZE_ON_START
                and self.bot
                and not getattr(self, 'initial_optimization_done', False)
            ):
                self.initial_optimization_done = True
                asyncio.create_task(self._run_initial_optimization())

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

        await self.run_backtest_simulation()

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

    def run_manual_optimization(self):
        if self.bot:
            self.log('🚀 Starting manual optimization…')
            ui.notify('Optimization started', type='info', position='bottom-right')
            asyncio.create_task(asyncio.to_thread(self.bot.run_optimization_thread))
        else:
            self.log('⚠️ No bot attached')

    def trigger_manual_close(self):
        if self.bot:
            self.bot.manual_close()
            self.log('👋 Manual close triggered')

    def trigger_kill_switch(self):
        if self.bot:
            self.bot.kill_switch()
            ui.notify('Kill switch activated!', type='negative', position='top')
            self.log('☠️ Kill switch triggered!')

    async def _run_initial_optimization(self):
        try:
            self.log('🤖 Auto-starting initial optimization…')
            self.btn_start.disable()
            self.bot.run_optimization_thread()
            while getattr(self.bot, 'is_optimizing', False):
                await asyncio.sleep(1.0)
            self.log('✅ Initial optimization complete — updating chart…')
            await self.run_backtest_simulation()
        except Exception as e:
            self.log(f'❌ Optimization failed: {e}')
        finally:
            self.btn_start.enable()

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
