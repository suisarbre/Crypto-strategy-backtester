"""
Optimization UI: search-space dialog, execution, results, fine-tuning.

Extracted from TradingDashboard, where it was 903 lines across 12 methods --
nearly half the class -- sitting alongside unrelated concerns like price
labels and log plumbing.
"""
import asyncio
import json
import os
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
from nicegui import ui

import config as cfg
from gui.state import report as _report
import strategies as strategies_pkg
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class OptimizationPanel:
    """Behaviour only — all state lives on the dashboard (see ADR-005)."""

    def __init__(self, dashboard):
        self.dash = dashboard

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

        strat_path = self.dash.active_strategy_path
        if not strat_path:
            strat_path = os.path.join(BASE_DIR, 'strategies', 'strategies.json')

        try:
            with open(strat_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            # Silently returning [] here renders an empty optimize panel with no
            # explanation — a malformed strategy JSON looked like a broken UI.
            _report(f'_extract_tunable_params: cannot read {strat_path}', e)
            self.dash.log(f'⚠️ Could not read strategy file: {os.path.basename(str(strat_path))}')
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

        self.dash._optim_checkboxes = {}
        self.dash._optim_range_inputs = {}
        self.dash._optim_dialog = None

        with ui.dialog().classes('optim-dialog') as dialog, \
             ui.card().classes('optim-card'):

            self.dash._optim_dialog = dialog

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
                    self.dash._optim_method = ui.toggle(
                        {0: 'Grid Search', 1: 'PSO (Swarm)'},
                        value=1 if getattr(cfg, 'USE_PSO', False) else 0,
                    ).props('dense no-caps').classes('text-xs')

                # ── Progress container (hidden initially) ──
                self.dash._optim_progress_container = ui.column().classes('w-full gap-2 mt-3')
                self.dash._optim_progress_container.set_visibility(False)

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
                self.dash._optim_checkboxes[param['name']] = cb

                ui.space()

                ui.label(f"Current: {param['current']}") \
                    .classes('optim-param-sub')

            # Range input
            range_str = ', '.join(str(v) for v in param['default_range'])
            inp = ui.input(
                label=f"{param['name']} values",
                value=range_str,
            ).props('dense outlined dark').classes('w-full mt-1 optim-range-input text-xs')
            self.dash._optim_range_inputs[param['name']] = inp

    async def _run_optimization_from_panel(self):
        """Collect checked params, build ranges, and run optimization."""
        # 1. Collect checked parameters
        selected_params = {}
        for pname, cb in self.dash._optim_checkboxes.items():
            if cb.value:
                raw = self.dash._optim_range_inputs[pname].value
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

        use_pso = self.dash._optim_method.value == 1

        # 2. Show progress
        self.dash._optim_progress_container.set_visibility(True)
        with self.dash._optim_progress_container:
            self.dash._optim_progress_container.clear()
            with ui.element('div').classes('optim-progress'):
                ui.spinner('dots', size='lg', color='blue')
                self.dash._optim_status_label = ui.label('Preparing optimization…') \
                    .classes('text-sm text-gray-300 mt-2')
                self.dash._optim_detail_label = ui.label('') \
                    .classes('text-xs text-gray-500 mt-1 font-mono')

        self.dash.log(f'🚀 Optimization started: {len(selected_params)} params ({"PSO" if use_pso else "Grid"}) — 4d optimize + 3d verify')

        # 3. Run optimization in background thread (chart keeps updating)
        try:
            result = await asyncio.to_thread(
                self._execute_panel_optimization, selected_params, use_pso
            )
            if result:
                self._show_optimization_results(result, selected_params)
            else:
                self.dash._optim_status_label.text = '❌ No valid results found — try wider search ranges'
                self.dash.log(f'❌ Optimization returned no valid results ({len(selected_params)} params)')
        except Exception as e:
            self.dash._optim_status_label.text = f'❌ Error: {e}'
            self.dash.log(f'❌ Optimization error: {e}')
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
        strat_path = self.dash.active_strategy_path
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
        self.dash._optim_progress_container.clear()
        self.dash._optim_progress_container.set_visibility(True)

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
        self.dash.log(log_msg)

        with self.dash._optim_progress_container:
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

                self.dash._new_name_input = ui.input(
                    label='New strategy name',
                    value=f'{self.dash.active_strategy_name}_optimized',
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
        self.dash._optim_progress_container.clear()
        self.dash._optim_progress_container.set_visibility(True)
        with self.dash._optim_progress_container:
            with ui.element('div').classes('optim-progress'):
                ui.spinner('dots', size='lg', color='purple')
                self.dash._optim_status_label = ui.label('Fine-tuning around best result…') \
                    .classes('text-sm text-gray-300 mt-2')
                # Show fine-tune ranges
                for pname, vals in fine_params.items():
                    ui.label(f'  {pname}: {vals}') \
                        .classes('text-xs text-gray-500 font-mono')

        self.dash.log(f'🔬 Fine-tuning {len(fine_params)} params around optimized values…')

        try:
            result = await asyncio.to_thread(
                self._execute_panel_optimization, fine_params, True  # always PSO for fine-tune
            )
            if result:
                # Compare with previous best
                prev_score = max(best_params.get('_prev_score', -999),
                                 sum(best_params.values()) * 0)  # just use 0 as fallback
                new_score = result.get('best_score', -999)
                self.dash.log(f'🔬 Fine-tune complete: score={new_score:.4f}')
                self._show_optimization_results(result, fine_params)
            else:
                self.dash._optim_status_label.text = '❌ Fine-tune found no valid results'
                self.dash.log('❌ Fine-tune returned no valid results')
        except Exception as e:
            self.dash._optim_status_label.text = f'❌ Error: {e}'
            self.dash.log(f'❌ Fine-tune error: {e}')
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
            if self.dash.bot:
                with self.dash.bot.lock:
                    self.dash.bot.state.config.update(cfg.CURRENT_CONFIG)
                    self.dash.bot.state.update_config(self.dash.bot.state.config)

            ui.notify('✅ Applied to current strategy', type='positive', position='bottom-right')
            self.dash.log(f'✅ Optimized params applied to {self.dash.active_strategy_name}')

        else:
            # Save as new strategy JSON in repository
            new_name = self.dash._new_name_input.value.strip()
            if not new_name:
                ui.notify('Enter a strategy name', type='warning')
                return

            repo_dir = os.path.join(BASE_DIR, 'strategies', 'repository')
            os.makedirs(repo_dir, exist_ok=True)
            safe_name = new_name.replace(' ', '_').lower()
            new_path = os.path.join(repo_dir, f'{safe_name}.json')

            # Load current strategy as base
            strat_path = self.dash.active_strategy_path or \
                os.path.join(BASE_DIR, 'strategies', 'strategies.json')
            try:
                with open(strat_path, 'r') as f:
                    data = json.load(f)
            except Exception:
                data = {}

            # Update strategy metadata
            data['strategy_name'] = new_name
            data['version'] = '1.0'
            data['comment'] = f'Optimized from {self.dash.active_strategy_name}'

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
            self.dash.log(f'✅ New strategy saved: {new_path}')

            # Refresh strategy list in sidebar.
            # Must stay a {key: label} dict to match how the selector is built —
            # assigning a bare key list here replaced the display names with raw
            # filename stems, and ChoiceElement._update_options() nulls the
            # current value whenever it is missing from the rebuilt key list.
            self.dash.available_strategies = self.dash._discover_strategies()
            self.dash.strategy_select.set_options(
                self.dash._strategy_options(),
                value=self.dash.active_strategy_name,
            )

        # Refresh chart
        if self.dash._optim_dialog:
            self.dash._optim_dialog.close()
        await self.dash.chart_panel.run_backtest_simulation()

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
            self.dash.log(f'❌ Could not apply params — unreadable strategy file: {path}')
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

    def run_manual_optimization(self):
        if self.dash.bot:
            self.dash.log('🚀 Starting manual optimization…')
            ui.notify('Optimization started', type='info', position='bottom-right')
            asyncio.create_task(asyncio.to_thread(self.dash.bot.run_optimization_thread))
        else:
            self.dash.log('⚠️ No bot attached')

    async def _run_initial_optimization(self):
        try:
            self.dash.log('🤖 Auto-starting initial optimization…')
            self.dash.btn_start.disable()
            self.dash.bot.run_optimization_thread()
            while getattr(self.dash.bot, 'is_optimizing', False):
                await asyncio.sleep(1.0)
            self.dash.log('✅ Initial optimization complete — updating chart…')
            await self.dash.chart_panel.run_backtest_simulation()
        except Exception as e:
            self.dash.log(f'❌ Optimization failed: {e}')
        finally:
            self.dash.btn_start.enable()
