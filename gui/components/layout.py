from nicegui import ui

# ═══════════════════════════════════════════════════════════════════════════════
# Theme Palette
# ═══════════════════════════════════════════════════════════════════════════════

THEME = {
    'bg_primary':    '#0a0e17',
    'bg_secondary':  '#111827',
    'bg_elevated':   '#1a2236',
    'bg_sidebar':    '#0d1321',
    'border':        '#1e293b',
    'text_primary':  '#e2e8f0',
    'text_secondary':'#94a3b8',
    'text_muted':    '#64748b',
    'accent_blue':   '#3b82f6',
    'positive':      '#10b981',
    'negative':      '#ef4444',
    'warning':       '#f59e0b',
}

# ═══════════════════════════════════════════════════════════════════════════════
# Global CSS
# ═══════════════════════════════════════════════════════════════════════════════

GLOBAL_CSS = '''
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    --bg-primary:    #0a0e17;
    --bg-secondary:  #111827;
    --bg-elevated:   #1a2236;
    --bg-sidebar:    #0d1321;
    --border:        #1e293b;
    --text-primary:  #e2e8f0;
    --text-secondary:#94a3b8;
    --accent-blue:   #3b82f6;
    --positive:      #10b981;
    --negative:      #ef4444;
  }

  /* ── Font: exclude Material Icons from override ── */
  body, button, input, select, textarea, div, span, p, a,
  h1, h2, h3, h4, h5, h6, label, li, td, th {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  }
  code, pre, .font-mono, .q-log {
    font-family: 'JetBrains Mono', monospace !important;
  }
  /* Ensure Material Icons always use their own font */
  .material-icons,
  .material-symbols-outlined,
  .q-icon,
  i.q-icon,
  i[class*="material"] {
    font-family: 'Material Icons' !important;
  }

  body, .q-page, .q-layout { background: var(--bg-primary) !important; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #475569; }

  /* ── Sidebar ── */
  .q-drawer {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border) !important;
  }

  /* ── Header ── */
  .q-header {
    background: linear-gradient(180deg, #0d1321 0%, #111827 100%) !important;
    border-bottom: 1px solid var(--border) !important;
  }

  /* ── KPI Cards ── */
  .kpi-card {
    background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-elevated) 100%) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    transition: transform 0.15s ease, border-color 0.25s ease;
  }
  .kpi-card:hover {
    transform: translateY(-1px);
    border-color: rgba(59,130,246,0.25) !important;
  }

  /* ── Buttons ── */
  .btn-modern {
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    text-transform: none !important;
    transition: all 0.15s ease !important;
    font-size: 13px !important;
    font-family: 'Inter', sans-serif !important;
  }
  .btn-modern:hover  { filter: brightness(1.12); }
  .btn-modern:active { transform: scale(0.98); }

  .btn-primary { background: linear-gradient(135deg, #3b82f6, #2563eb) !important; }
  .btn-success { background: linear-gradient(135deg, #10b981, #059669) !important; }
  .btn-danger  { background: linear-gradient(135deg, #ef4444, #dc2626) !important; }
  .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706) !important; }
  .btn-purple  { background: linear-gradient(135deg, #8b5cf6, #7c3aed) !important; }
  .btn-ghost {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    color: var(--text-secondary) !important;
  }
  .btn-ghost:hover {
    border-color: var(--accent-blue) !important;
    color: var(--text-primary) !important;
  }

  /* ── Section headers ── */
  .section-label {
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #64748b !important;
    padding: 2px 0 6px 2px !important;
    font-family: 'Inter', sans-serif !important;
  }

  /* ── Status Badge ── */
  .status-badge {
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    padding: 4px 14px !important;
    border-radius: 20px !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 6px !important;
    white-space: nowrap !important;
    font-family: 'Inter', sans-serif !important;
  }
  .status-stopped { background: rgba(239,68,68,0.12) !important; color: #ef4444 !important; border: 1px solid rgba(239,68,68,0.25) !important; }
  .status-running { background: rgba(16,185,129,0.12) !important; color: #10b981 !important; border: 1px solid rgba(16,185,129,0.25) !important; }
  .status-paused  { background: rgba(245,158,11,0.12) !important; color: #f59e0b !important; border: 1px solid rgba(245,158,11,0.25) !important; }
  .status-killed  { background: rgba(239,68,68,0.20) !important; color: #fca5a5 !important; border: 1px solid rgba(239,68,68,0.35) !important; }

  /* ── Log Panel ── */
  .log-panel {
    background: var(--bg-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
  }
  .log-panel .nicegui-log {
    background: transparent !important;
    font-size: 12px !important;
    line-height: 1.7 !important;
  }
  .log-panel .nicegui-log label {
    color: var(--text-secondary) !important;
    font-size: 12px !important;
  }

  /* ── Chart Container ── */
  .chart-container {
    background: var(--bg-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
  }

  /* ── Separator ── */
  .q-separator { background: var(--border) !important; opacity: 0.5; }

  /* ── Select inputs ── */
  .q-field--dark .q-field__control {
    background: var(--bg-elevated) !important;
    border-radius: 8px !important;
  }

  /* ── Expansion Panel (Log toggle) ── */
  .log-expansion .q-expansion-item__container {
    background: transparent !important;
  }
  .log-expansion .q-item {
    padding: 6px 12px !important;
    min-height: 36px !important;
  }
  .log-expansion .q-item__label {
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #64748b !important;
    font-family: 'Inter', sans-serif !important;
  }
  .log-expansion .q-expansion-item__content {
    padding: 0 !important;
  }

  /* ── Bottom action bar ── */
  .action-bar {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 10px 16px !important;
  }

  /* ── Pulse animation ── */
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }
  .pulse-dot {
    width: 7px; height: 7px; border-radius: 50%;
    display: inline-block;
    animation: pulse-dot 2s ease-in-out infinite;
  }

  /* ── Notification ── */
  .q-notification { border-radius: 10px !important; font-weight: 500 !important; }

  /* ══════════════════════════════════════════════════════════════════════════
     BENCHMARK DRAWER  (right-side sliding panel)
     ══════════════════════════════════════════════════════════════════════════ */
  .q-drawer--right {
    background: var(--bg-sidebar) !important;
    border-left: 1px solid var(--border) !important;
  }

  .bench-header {
    font-size: 11px; font-weight: 700; letter-spacing: 0.10em;
    text-transform: uppercase; color: #64748b;
    padding: 0 0 8px 0;
  }

  /* Metric row: label + value + comparison bar */
  .bench-metric {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    transition: border-color 0.2s ease;
  }
  .bench-metric:hover {
    border-color: rgba(59,130,246,0.3);
  }
  .bench-metric-label {
    font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #64748b;
    font-family: 'Inter', sans-serif;
  }
  .bench-metric-value {
    font-size: 16px; font-weight: 700; color: #e2e8f0;
    font-family: 'JetBrains Mono', monospace;
    line-height: 1.2;
  }
  .bench-metric-sub {
    font-size: 11px; font-weight: 500; color: #94a3b8;
    font-family: 'JetBrains Mono', monospace;
  }

  /* Comparison bar (strategy vs baseline) */
  .bench-bar-track {
    height: 6px; border-radius: 3px;
    background: rgba(255,255,255,0.06);
    position: relative; overflow: hidden;
  }
  .bench-bar-fill {
    height: 100%; border-radius: 3px;
    transition: width 0.5s ease;
  }
  .bench-bar-strategy { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
  .bench-bar-baseline { background: linear-gradient(90deg, #64748b, #94a3b8); }

  /* Alpha badge */
  .alpha-badge {
    font-size: 13px; font-weight: 700;
    padding: 8px 16px; border-radius: 8px;
    text-align: center;
    font-family: 'JetBrains Mono', monospace;
  }
  .alpha-positive {
    background: rgba(16,185,129,0.12); color: #10b981;
    border: 1px solid rgba(16,185,129,0.25);
  }
  .alpha-negative {
    background: rgba(239,68,68,0.12); color: #ef4444;
    border: 1px solid rgba(239,68,68,0.25);
  }

  /* Verdict card */
  .bench-verdict {
    background: linear-gradient(135deg, var(--bg-secondary), var(--bg-elevated));
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    text-align: center;
  }
  .bench-verdict-title {
    font-size: 10px; font-weight: 700; letter-spacing: 0.10em;
    text-transform: uppercase; color: #64748b;
  }
  .bench-verdict-text {
    font-size: 13px; font-weight: 600; margin-top: 4px;
    font-family: 'Inter', sans-serif;
  }

  /* Toggle button in header */
  .bench-toggle {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: #94a3b8 !important;
    font-size: 12px !important;
    padding: 4px 12px !important;
    transition: all 0.15s ease !important;
    font-family: 'Inter', sans-serif !important;
  }
  .bench-toggle:hover {
    border-color: var(--accent-blue) !important;
    color: var(--text-primary) !important;
  }
  .bench-toggle-active {
    border-color: var(--accent-blue) !important;
    color: var(--accent-blue) !important;
    background: rgba(59,130,246,0.08) !important;
  }

  /* ══════════════════════════════════════════════════════════════════════════
     OPTIMIZATION DIALOG (full-screen overlay)
     ══════════════════════════════════════════════════════════════════════════ */
  .optim-dialog .q-dialog__inner {
    padding: 0 !important;
  }
  .optim-card {
    background: var(--bg-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    max-width: 720px !important;
    width: 720px !important;
    max-height: 85vh !important;
    overflow: hidden !important;
  }
  .optim-card-inner {
    max-height: calc(85vh - 120px);
    overflow-y: auto;
    padding: 0 24px 16px 24px;
  }
  .optim-section-title {
    font-size: 11px; font-weight: 700; letter-spacing: 0.10em;
    text-transform: uppercase; color: #64748b;
    padding: 12px 0 6px 0;
    font-family: 'Inter', sans-serif;
  }
  .optim-param-row {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    transition: border-color 0.2s ease;
  }
  .optim-param-row:hover {
    border-color: rgba(59,130,246,0.25);
  }
  .optim-param-label {
    font-size: 13px; font-weight: 600; color: #e2e8f0;
    font-family: 'Inter', sans-serif;
  }
  .optim-param-sub {
    font-size: 10px; color: #64748b;
    font-family: 'JetBrains Mono', monospace;
  }
  .optim-range-input .q-field__control {
    background: var(--bg-secondary) !important;
    border-radius: 6px !important;
  }
  .optim-progress {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }
  .optim-result-card {
    background: linear-gradient(135deg, var(--bg-secondary), var(--bg-elevated));
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }
</style>
'''


class AppLayout:
    """Builds the dashboard shell: header + sidebar (strategy only)."""

    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.build()

    def build(self):
        # ── Inject Global Styles ──
        ui.add_head_html(GLOBAL_CSS)

        # ══════════════════════════════════════════════════════════════════════
        #  HEADER
        # ══════════════════════════════════════════════════════════════════════
        with ui.header().classes('row items-center px-6 py-0') as header:
            header.style('height: 50px; min-height: 50px;')

            # Brand
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.icon('candlestick_chart', size='22px').classes('text-blue-400')
                ui.label('TradeBot').classes('text-base font-bold text-white tracking-wide')

            ui.space()

            # Live Price
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.html('<span class="pulse-dot" style="background:#10b981;"></span>')
                self.dashboard.price_label = (
                    ui.label('0.00 USDT')
                    .classes('text-base font-bold font-mono text-white tracking-wide')
                )

            ui.space()

            # Balance
            with ui.row().classes('items-center gap-2 no-wrap mr-4'):
                ui.icon('account_balance_wallet', size='16px').classes('text-gray-500')
                self.dashboard.balance_label = (
                    ui.label('$100.00 (0.00%)')
                    .classes('text-sm font-mono font-semibold text-gray-300')
                )

            # Status Badge
            self.dashboard.status_label = (
                ui.label('STOPPED')
                .classes('status-badge status-stopped')
            )

            # Benchmark Toggle Button
            self.dashboard.bench_toggle_btn = (
                ui.button('', on_click=self._toggle_benchmark_drawer)
                .props('unelevated icon=analytics flat dense')
                .classes('bench-toggle ml-2')
                .tooltip('Strategy Benchmarks')
            )

        # ══════════════════════════════════════════════════════════════════════
        #  SIDEBAR  — Strategy & Chart tools only
        # ══════════════════════════════════════════════════════════════════════
        with ui.left_drawer(value=True).classes('px-3 pt-4 pb-6') as drawer:
            drawer.style('width: 240px;')

            # ── Strategy Selector ──
            ui.label('STRATEGY').classes('section-label')
            with ui.column().classes('w-full gap-2'):
                self.dashboard.available_strategies = self.dashboard._discover_strategies()
                # {key: label} — the selector's value stays the canonical key
                # (filename stem); the JSON's strategy_name is display only.
                strat_options = self.dashboard._strategy_options()

                self.dashboard.strategy_select = (
                    ui.select(
                        options=strat_options,
                        value=self.dashboard.active_strategy_name,
                        label='Active Strategy',
                    )
                    .props('dense dark outlined')
                    .classes('w-full')
                )

                ui.button('Apply & Preview', on_click=self.dashboard._apply_strategy) \
                    .props('unelevated icon=swap_horiz') \
                    .classes('w-full btn-modern btn-ghost')

                # Strategy info mini-card
                with ui.element('div').classes('w-full rounded-lg p-3 mt-1') \
                        .style(f'background:{THEME["bg_elevated"]};border:1px solid {THEME["border"]};'):
                    self.dashboard.strat_info_label = (
                        ui.label(f'Active: {self.dashboard.active_strategy_name}')
                        .classes('text-xs font-mono text-gray-300')
                    )
                    self.dashboard.strat_stats_label = (
                        ui.label('Stats: --')
                        .classes('text-xs font-mono text-gray-500 mt-1')
                    )

            ui.separator().classes('my-4')

            # ── Chart Tools ──
            ui.label('CHART').classes('section-label')
            with ui.column().classes('w-full gap-2'):
                ui.button('Load Data & Strategy', on_click=self.dashboard.chart_panel.run_backtest_simulation) \
                    .props('unelevated icon=insights') \
                    .classes('w-full btn-modern btn-purple text-white')
                ui.button('Reload Chart', on_click=self.dashboard.chart_panel.init_chart) \
                    .props('unelevated icon=refresh') \
                    .classes('w-full btn-modern btn-ghost')

            ui.separator().classes('my-4')

            # ── Optimization ──
            ui.label('OPTIMIZATION').classes('section-label')
            with ui.column().classes('w-full gap-2'):
                ui.button('Optimize Strategy', on_click=self.dashboard.optimization.open_optimization_dialog) \
                    .props('unelevated icon=tune') \
                    .classes('w-full btn-modern btn-primary text-white')

            # ── Spacer + Shutdown ──
            ui.space()
            ui.separator().classes('my-3')
            ui.button('Shutdown', on_click=self.dashboard.shutdown_app) \
                .props('unelevated icon=power_settings_new') \
                .classes('w-full btn-modern text-white') \
                .style('background:linear-gradient(135deg,#7f1d1d,#991b1b)!important;border:1px solid rgba(220,38,38,0.4);')

        # ══════════════════════════════════════════════════════════════════════
        #  BENCHMARK DRAWER  — right-side sliding panel
        # ══════════════════════════════════════════════════════════════════════
        with ui.right_drawer(value=False, fixed=True) \
                .classes('px-3 pt-4 pb-6') \
                .props('bordered overlay behavior=desktop width=320') as bench_drawer:
            self.dashboard.bench_drawer = bench_drawer

            # ── Title ──
            with ui.row().classes('w-full items-center no-wrap mb-3'):
                ui.icon('analytics', size='18px').classes('text-blue-400')
                ui.label('Benchmarks').classes('text-sm font-bold text-white tracking-wide')
                ui.space()
                ui.button(icon='close', on_click=lambda: self._toggle_benchmark_drawer()) \
                    .props('flat dense round size=sm') \
                    .classes('text-gray-500')

            ui.separator().classes('mb-3')

            # ── Placeholder: populated by dashboard.py after backtest ──
            self.dashboard.bench_container = ui.column().classes('w-full gap-3')

            with self.dashboard.bench_container:
                with ui.element('div').classes('w-full text-center py-8'):
                    ui.icon('trending_up', size='32px').classes('text-gray-600')
                    ui.label('Run a backtest to see benchmarks') \
                        .classes('text-xs text-gray-500 mt-2')

    def _toggle_benchmark_drawer(self):
        self.dashboard.bench_drawer.toggle()
        # Toggle active class on button
        is_open = self.dashboard.bench_drawer.value
        if is_open:
            self.dashboard.bench_toggle_btn.classes(add='bench-toggle-active')
        else:
            self.dashboard.bench_toggle_btn.classes(remove='bench-toggle-active')
