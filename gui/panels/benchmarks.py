"""
Benchmark comparison: strategy metrics vs buy-and-hold and a risk-free proxy.

Risk-adjusted ratios (Sortino, Calmar, profit factor) come from the C++ engine;
without it the panel falls back to the Python backtester and reports those
three as unavailable rather than as zero.
"""
import numpy as np
from nicegui import ui

import config as cfg


class BenchmarksPanel:
    """Behaviour only — all state lives on the dashboard (see ADR-005)."""

    def __init__(self, dashboard):
        self.dash = dashboard

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

        self.dash.bench_container.clear()

        alpha = strategy['total_return'] - baseline['buy_hold_return']
        rf_alpha = strategy['total_return'] - baseline['risk_free_return']

        with self.dash.bench_container:
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

    def _bench_row(self, label, value, *, sub=None, color='#e2e8f0'):
        with ui.element('div').classes('bench-metric'):
            ui.label(label).classes('bench-metric-label')
            ui.label(value).classes('bench-metric-value').style(f'color:{color};')
            if sub:
                ui.label(sub).classes('bench-metric-sub')

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
