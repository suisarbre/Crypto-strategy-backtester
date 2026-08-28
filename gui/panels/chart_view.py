"""
Chart lifecycle and data loading: mount, backtest-and-render, live candle
updates, and the OHLCV disk cache.

The heavy pipeline that used to be a closure inside run_backtest_simulation
now lives in gui/panels/chart_data.py as a plain function, so it can be
tested without NiceGUI.
"""
import asyncio
import os
import time

import pandas as pd
from nicegui import ui

import config as cfg
from gui.state import report as _report
from data.data_loader import fetch_raw_data
from gui.panels.chart_data import build_chart_payload


class ChartPanel:
    """Behaviour only — all state lives on the dashboard (see ADR-005)."""

    def __init__(self, dashboard):
        self.dash = dashboard

    async def init_chart(self):
        if self.dash.chart:
            self.dash.chart.init_chart()
        self.dash.log('✅ Chart mounted')

        # Cancel any previously scheduled backtest timer
        if hasattr(self, '_init_timer') and self.dash._init_timer:
            self.dash._init_timer.cancel()
        self.dash._init_timer = ui.timer(1.0, self.run_backtest_simulation, once=True)

    async def run_backtest_simulation(self):
        # ── Guard: prevent concurrent / re-entrant runs ──
        if getattr(self, '_backtest_running', False):
            self.dash._backtest_pending = True          # single dedup'd retry
            # A full load takes ~20s, so this window is wide: clicking
            # "Apply & Preview" during one silently left the previous strategy's
            # chart on screen, which read as the swap being ignored.
            self.dash.log('⏳ A load is already running — queued; chart will refresh when it finishes')
            return False
        self.dash._backtest_running = True
        self.dash._backtest_pending = False
        self.dash._backtest_start_time = time.time()

        # ── Pause live chart updates while the full backtest runs ──
        if hasattr(self, 'update_timer') and self.dash.update_timer:
            try:
                self.dash.update_timer.cancel()
            except Exception as e:
                _report('run_backtest_simulation: could not cancel chart timer', e)
            self.dash.update_timer = None

        try:
            limit = cfg.MAX_FETCH_LIMIT
            strat_name = self.dash.active_strategy_name
            self.dash.log(f'Loading {cfg.SYMBOL} ({cfg.TIMEFRAME}) — strategy: {strat_name}…')

            strategy_json_content = None
            if self.dash.active_strategy_path:
                try:
                    with open(self.dash.active_strategy_path, 'r') as f:
                        strategy_json_content = f.read()
                except Exception as e:
                    self.dash.log(f'Error loading strategy: {e}')

            _strat_json = strategy_json_content

            def _heavy_loader():
                """Fetch + run the pipeline off the event loop."""
                df = self.fetch_and_cache_data(cfg.SYMBOL, cfg.TIMEFRAME, limit)
                if df is None or df.empty:
                    return None, None, None, None, 0, 0
                if len(df) > limit:
                    df = df.tail(limit).copy().reset_index(drop=True)
                config = (
                    self.dash.bot.state.config.copy() if self.dash.bot
                    else cfg.CURRENT_CONFIG.copy()
                )
                return build_chart_payload(df, config, strategy_json=_strat_json)

            self.dash.log(f'Processing data (strategy: {strat_name})…')
            result = await asyncio.to_thread(_heavy_loader)

            # Unpack — _heavy_loader returns a tuple
            if result[0] is None:
                self.dash.log('❌ Failed to fetch data')
                return

            df, bt_config, chart_data, all_markers, n_signals, n_trades = result

            self.dash.log(f'Processing {len(df)} bars…')

            self.dash.chart_markers = all_markers

            # Update KPI
            if hasattr(self, '_kpi_trades'):
                self.dash._kpi_trades.text = str(n_trades)

            if self.dash.chart:
                try:
                    self.dash.chart.set_data(chart_data)
                    if self.dash.chart_markers:
                        self.dash.chart.set_markers(self.dash.chart_markers)
                        self.dash.log(f'✅ {n_signals} signals + {n_trades} trade markers applied')
                except RuntimeError:
                    self.dash.log('⚠️ Chart update skipped (client disconnected)')
                    return

            self.dash.history_data = chart_data
            self.dash.current_price = chart_data[-1]['close'] if chart_data else 0
            self.dash.update_price_label(self.dash.current_price)

            if hasattr(self, 'update_timer') and self.dash.update_timer:
                self.dash.update_timer.cancel()
            self.dash.update_timer = ui.timer(
                cfg.CHART_UPDATE_INTERVAL_SEC, self.update_chart_loop
            )
            self.dash.log('✅ Live chart updates started (trading paused)')

            # ── Compute & display benchmark comparison ──
            try:
                strat_m, base_m = await asyncio.to_thread(
                    self.dash.benchmarks._compute_benchmarks, df, bt_config,
                )
                if strat_m and base_m:
                    self.dash.benchmarks._populate_benchmarks(strat_m, base_m)  # UI update — must run on main loop
                    sortino = strat_m['sortino']
                    sortino_txt = f'{sortino:.2f}' if sortino is not None else 'n/a (no C++ engine)'
                    self.dash.log(
                        f'📊 Benchmarks: Return {strat_m["total_return"]:+.2f}% '
                        f'| α {strat_m["total_return"] - base_m["buy_hold_return"]:+.2f}% '
                        f'| Sortino {sortino_txt}'
                    )
                else:
                    self.dash.log('⚠️ Benchmark computation returned no data')
            except Exception as e:
                self.dash.log(f'⚠️ Benchmark computation skipped: {e}')

            if (
                cfg.AUTO_OPTIMIZE_ON_START
                and self.dash.bot
                and not getattr(self, 'initial_optimization_done', False)
            ):
                self.dash.initial_optimization_done = True
                asyncio.create_task(self.dash.optimization._run_initial_optimization())

        except Exception as e:
            self.dash.log(f'❌ Simulation error: {e}')
            import traceback
            traceback.print_exc()
        finally:
            self.dash._backtest_running = False
            # If another caller requested a run while we were busy, do ONE retry
            if getattr(self, '_backtest_pending', False):
                self.dash._backtest_pending = False
                ui.timer(0.5, self.run_backtest_simulation, once=True)

    async def update_chart_loop(self):
        if getattr(self, 'is_updating_chart', False):
            return
        try:
            self.dash.is_updating_chart = True
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
                if self.dash.chart:
                    try:
                        self.dash.chart.update_candle(candle)
                    except RuntimeError:
                        # Expected: client disconnected. This fires on every
                        # poll until the loop is torn down, so it stays silent
                        # by design rather than by omission.
                        pass

                self.dash.update_price_label(last_row['close'])

                config = (
                    self.dash.bot.state.config.copy() if self.dash.bot
                    else cfg.CURRENT_CONFIG.copy()
                )

                _strat_path = self.dash.active_strategy_path
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
                        self.dash.log('⚠️ Chart markers using default rules — '
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
                    self.dash.chart_markers = []

                if not latest_df.empty:
                    min_ts = int(latest_df['timestamp'].iloc[0].timestamp())
                    max_ts = int(latest_df['timestamp'].iloc[-1].timestamp())

                    kept = [
                        m for m in self.dash.chart_markers
                        if m['time'] < min_ts or m['time'] > max_ts
                    ]
                    kept.extend(cleaned_markers)
                    self.dash.chart_markers = sorted(kept, key=lambda x: x['time'])

                    if self.dash.chart:
                        try:
                            self.dash.chart.set_markers(self.dash.chart_markers)
                        except RuntimeError:
                            # Expected: client disconnected — see above.
                            pass

        except Exception as e:
            print(f'Update error: {e}')
            import traceback
            traceback.print_exc()
        finally:
            self.dash.is_updating_chart = False

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
