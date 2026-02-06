from nicegui import ui, app
import asyncio
from datetime import datetime, timedelta
import random
import json
import sys
import os
import pandas as pd

# [Path Fix] Add parent directory to path to allow imports from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
import config as cfg

# ==============================================================================
# [GUI Dashboard for Trading Bot]
# ==============================================================================

# [Theme Colors]
THEME = {
    'primary': '#5898d4',
    'secondary': '#26a69a',
    'accent': '#ef5350',
    'dark': '#1d1e22',
    'positive': '#21ba45',
    'negative': '#c10015',
    'info': '#31ccec',
    'warning': '#f2c037'
}

# 1. Load Library (Pinned to v4.1.1 for stability)
ui.add_head_html('<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>')

# 2. Define Global JavaScript Functions
ui.add_body_html('''
<script>
    let chart = null;
    let candleSeries = null;

    // A. Initialize Chart
    window.initChartGlobal = function() {
        const container = document.getElementById('tv-chart');
        if (!container) return;
        
        // Debug Indicator
        const debug = document.createElement('div');
        debug.id = 'chart-debug';
        debug.style.cssText = "position:absolute; top:5px; left:5px; z-index:999; color:yellow; background:rgba(0,0,0,0.7); padding:5px;";
        debug.innerText = "⏳ Initializing...";
        container.appendChild(debug);

        // Check Library
        if (!window.LightweightCharts) {
            debug.innerText = "❌ Library NOT Loaded";
            return;
        }

        const chartDiv = document.createElement('div');
        chartDiv.id = 'chart-wrapper';
        chartDiv.style.cssText = "width: 100%; height: 100%;";
        container.appendChild(chartDiv);

        window.chart = LightweightCharts.createChart(chartDiv, {
            layout: { textColor: '#d1d4dc', background: { type: 'solid', color: '#111111' } },
            grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
            timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#485c7b' },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        });

        window.candleSeries = window.chart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
        });

        new ResizeObserver(entries => {
            if (entries.length === 0 || entries[0].target !== chartDiv) return;
            const newRect = entries[0].contentRect;
            window.chart.applyOptions({ height: newRect.height, width: newRect.width });
        }).observe(chartDiv);

        debug.innerText = "✅ Chart Ready (v4.1.1)";
        debug.style.color = "#0f0";
    }

    // B. Set Data
    window.setChartDataGlobal = function(data) {
        if (window.candleSeries) {
            window.candleSeries.setData(data);
            window.chart.timeScale().fitContent();
            const debug = document.getElementById('chart-debug');
            if(debug) debug.innerText = "✅ Data Loaded: " + data.length;
        }
    }

    // C. Update Candle
    window.updateCandleGlobal = function(candle) {
        if (window.candleSeries) window.candleSeries.update(candle);
    }
    
    // D. Set Markers
    window.setMarkersGlobal = function(markers) {
        if (window.candleSeries) window.candleSeries.setMarkers(markers);
    }
</script>
''')

class TradingDashboard:
    def __init__(self):
        self.is_running = False
        self.history_data = [] 
        
        # Ensure data directory exists
        if not os.path.exists('chart_data'):
            os.makedirs('chart_data')
            
        self.build_ui()
        
        # Init Sequence
        ui.timer(0.5, self.init_chart, once=True)

    def fetch_and_cache_data(self, symbol, timeframe, limit=5000):
        """
        Smart Fetch: Loads CSV -> Fetches Missing Data -> Saves CSV -> Returns DF
        Example: chart_data/BTC_USDT_5m.csv
        """
        safe_symbol = symbol.replace('/', '_')
        file_path = f"chart_data/{safe_symbol}_{timeframe}.csv"
        
        existing_df = pd.DataFrame()
        since = None
        
        # 1. Load Cache
        if os.path.exists(file_path):
            try:
                existing_df = pd.read_csv(file_path)
                existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
                if not existing_df.empty:
                    last_time = existing_df['timestamp'].iloc[-1]
                    since = int(last_time.timestamp() * 1000) + 1 # Next ms
                    self.log(f"📁 Cache Found! Last Candle: {last_time}")
            except Exception as e:
                self.log(f"⚠️ Cache Load Error: {e}")
        
        # 2. Fetch New Data (or Initial limit)
        if existing_df.empty:
             self.log(f"🌐 Fetching fresh data ({limit} candles)...")
             new_df = fetch_raw_data(symbol, timeframe, limit)
        else:
             # Fetch only what's new (Limit is just safety cap here)
             self.log(f"🌐 Fetching updates since {since}...")
             new_df = fetch_raw_data(symbol, timeframe, max(100, limit)) # Just fetch valid amount
        
        if new_df is None or new_df.empty:
            return existing_df if not existing_df.empty else None
            
        # 3. Merge & Deduplicate
        if not existing_df.empty:
            combined = pd.concat([existing_df, new_df])
            combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
            combined = combined.sort_values(by='timestamp').reset_index(drop=True)
            final_df = combined
        else:
            final_df = new_df
            
        # 4. Save Cache
        try:
            final_df.to_csv(file_path, index=False)
            self.log(f"💾 Saved {len(final_df)} candles to {file_path}")
        except Exception as e:
            self.log(f"❌ Save Error: {e}")
            
        return final_df

    def build_ui(self):
        # [Header]
        with ui.header().classes('row items-center') as header:
            header.style(f'background-color: {THEME["dark"]}')
            ui.icon('show_chart', size='32px').classes('text-white')
            ui.label('TRADING BOT DASHBOARD').classes('text-h6 text-white font-bold ml-2')
            
            ui.space()
            self.price_label = ui.label('0.00 USDT').classes('text-h6 text-white mr-8 font-mono font-bold')
            self.status_label = ui.label('STOPPED').classes('text-red-500 font-bold mr-4 border border-red-500 px-2 rounded')

        # [Sidebar]
        with ui.left_drawer(value=True).classes('bg-gray-100') as drawer:
            ui.label('CONTROLS').classes('text-h6 font-bold m-4 text-gray-700')
            with ui.column().classes('w-full px-4 gap-4'):
                self.btn_start = ui.button('START', on_click=self.start_bot).props('push color=positive icon=play_arrow').classes('w-full h-12')
                self.btn_stop = ui.button('STOP', on_click=self.stop_bot).props('push color=negative icon=stop').classes('w-full h-12')
                ui.separator().classes('my-4')
                ui.button('SHOW DATA & STRATEGY', on_click=self.run_backtest_simulation).classes('w-full bg-purple-600 text-white font-bold')
                ui.button('RELOAD CHART', on_click=self.init_chart).classes('w-full bg-gray-500 text-white')

        # [Main Content]
        with ui.column().classes('w-full h-[calc(100vh-64px)] p-4 bg-gray-900 no-wrap'):
            # Chart Container
            with ui.card().classes('w-full flex-grow bg-black border-gray-700 p-0 overflow-hidden relative'):
                ui.element('div').props('id=tv-chart').classes('w-full h-full').style('min-height: 500px;')

            # Logs
            with ui.card().classes('w-full h-48 mt-4 bg-gray-800 text-white scroll-y-auto'):
                ui.label('LOGS').classes('text-xs font-bold text-gray-400 sticky top-0 bg-gray-800 p-1 block w-full')
                self.log_container = ui.log().classes('w-full font-mono text-sm p-2')

    def init_chart(self):
        # Call global JS function
        ui.run_javascript('window.initChartGlobal()')
        self.log("Initializing Chart (JS called)...")

    def run_backtest_simulation(self):
        try:
            limit = 5000 
            self.log(f"Loading Data for {cfg.SYMBOL} ({cfg.TIMEFRAME})...")
            
            # 1. Fetch & Cache Data
            df = self.fetch_and_cache_data(cfg.SYMBOL, cfg.TIMEFRAME, limit)
            
            if df is None or df.empty:
                self.log("❌ Error: Failed to fetch data.")
                return
                
            # Limit display to last N candles to prevent browser lag if cache is huge
            if len(df) > limit:
                df = df.tail(limit).copy().reset_index(drop=True)
                
            # 2. Apply Strategy
            self.log("Applying Strategy Indicators & Signals...")
            config = cfg.CURRENT_CONFIG.copy() 
            df = add_indicators(df, config)
            df = generate_signals(df, config)
            
            # 3. Chart Data
            chart_data = []
            for idx, row in df.iterrows():
                ts = int(row['timestamp'].timestamp())
                chart_data.append({
                    'time': ts, 'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close']
                })
                
            # 4. Simulate Trades & Markers
            markers = []
            position = 0 # 0, 1, -1
            partial_done = False
            entry_price = 0.0
            ts_price = 0.0 # [NEW] Trailing Stop Price
            
            # SL & TS Config
            sl_ratio = getattr(cfg, 'SL_RATIO', 0.03)
            leverage = getattr(cfg, 'DEFAULT_LEVERAGE', 3)
            ts_mult = getattr(cfg, 'ATR_TRAIL_MULTIPLIER', 3.0)
            
            stats = {'long': 0, 'short': 0, 'exit': 0, 'sl': 0, 'partial': 0, 'ts': 0}
            
            for idx, row in df.iterrows():
                ts = int(row['timestamp'].timestamp())
                sig = row['final_signal']
                close = row['close']
                low = row['low']
                high = row['high']
                atr = row['atr'] if 'atr' in row else 0 # Ensure ATR exists
                
                # A. Check Exits (SL or TS)
                if position != 0:
                    
                    # 1. Trailing Stop Check (Only if partial_done)
                    if partial_done:
                        if position == 1: # Long
                            new_ts = high - (atr * ts_mult) # Use High to be aggressive? No, usually Close or High.
                            # Standard Logic: Price - ATR. 
                            new_ts = close - (atr * ts_mult) 
                            if new_ts > ts_price: ts_price = new_ts
                            
                            if low <= ts_price: # Hit TS
                                position = 0
                                stats['ts'] += 1
                                markers.append({'time': ts, 'position': 'aboveBar', 'color': 'purple', 'shape': 'circle', 'text': 'TS'})
                                continue
                                
                        elif position == -1: # Short
                            new_ts = close + (atr * ts_mult)
                            if ts_price == 0 or new_ts < ts_price: ts_price = new_ts
                            
                            if high >= ts_price: # Hit TS
                                position = 0
                                stats['ts'] += 1
                                markers.append({'time': ts, 'position': 'belowBar', 'color': 'purple', 'shape': 'circle', 'text': 'TS'})
                                continue
                                
                    # 2. Hard Stop Loss Check (Only if NOT partial_done or failsafe)
                    # (Assuming TS replaces SL after partial)
                    else:
                        if position == 1:
                            pnl = (low - entry_price) / entry_price
                            lev_pnl = pnl * leverage
                            if lev_pnl <= -sl_ratio:
                                position = 0
                                stats['sl'] += 1
                                markers.append({'time': ts, 'position': 'belowBar', 'color': '#c10015', 'shape': 'circle', 'text': 'SL'})
                                continue
                        elif position == -1:
                            pnl = (entry_price - high) / entry_price
                            lev_pnl = pnl * leverage
                            if lev_pnl <= -sl_ratio:
                                position = 0
                                stats['sl'] += 1
                                markers.append({'time': ts, 'position': 'aboveBar', 'color': '#c10015', 'shape': 'circle', 'text': 'SL'})
                                continue

                # B. Signal Processing
                if position == 0:
                    if sig == 1:
                        position = 1
                        partial_done = False
                        entry_price = close
                        # Init TS check value (loose)
                        ts_price = close - (atr * ts_mult)
                        stats['long'] += 1
                        markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'LONG'})
                    elif sig == -1:
                        position = -1
                        partial_done = False
                        entry_price = close
                        ts_price = close + (atr * ts_mult)
                        stats['short'] += 1
                        markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'SHORT'})
                        
                elif position == 1: # Holdings Long
                    if sig == -1: # Reverse Short
                        position = -1
                        partial_done = False
                        entry_price = close
                        ts_price = close + (atr * ts_mult)
                        stats['short'] += 1
                        markers.append({'time': ts, 'position': 'aboveBar', 'color': '#ef5350', 'shape': 'arrowDown', 'text': 'Rev SHORT'})
                    elif sig == 0: # Partial Exit
                        if not partial_done:
                            partial_done = True
                            stats['partial'] += 1
                            # Move TS to Breakeven
                            ts_price = max(ts_price, entry_price) 
                            markers.append({'time': ts, 'position': 'aboveBar', 'color': '#f2c037', 'shape': 'square', 'text': 'Partial'})
                            
                elif position == -1: # Holding Short
                    if sig == 1: # Reverse Long
                        position = 1
                        partial_done = False
                        entry_price = close
                        ts_price = close - (atr * ts_mult)
                        stats['long'] += 1
                        markers.append({'time': ts, 'position': 'belowBar', 'color': '#21ba45', 'shape': 'arrowUp', 'text': 'Rev LONG'})
                    elif sig == 0: # Partial Exit
                        if not partial_done:
                            partial_done = True
                            stats['partial'] += 1
                            ts_price = min(ts_price, entry_price)
                            markers.append({'time': ts, 'position': 'belowBar', 'color': '#f2c037', 'shape': 'square', 'text': 'Partial'})

            # 5. Send to Chart
            self.log(f"Simulated: {stats['long']}L / {stats['short']}S / {stats['partial']}P / {stats['sl']}SL / {stats['ts']}TS")

            # 5. Send to Chart
            self.log(f"Simulated: {stats['long']}L / {stats['short']}S / {stats['partial']}P / {stats['sl']}SL")
            
            # Batch send to prevent freezing? No, 5000 is fine usually.
            ui.run_javascript(f'window.setChartDataGlobal({json.dumps(chart_data)})')
            
            if len(markers) > 0:
                def send_markers():
                    ui.run_javascript(f'window.setMarkersGlobal({json.dumps(markers)})')
                    self.log(f"✅ Markers Sent: {len(markers)}")
                
                ui.timer(0.5, send_markers, once=True)
            else:
                self.log("⚠️ No Trades detected in this period (No Markers).")
            
            self.history_data = chart_data
            self.current_price = chart_data[-1]['close']
            self.update_price_label(self.current_price)
            
            # Start Real-time Update Loop
            self.is_running = True
            
            # Cancel existing timer if any
            if hasattr(self, 'update_timer') and self.update_timer:
                self.update_timer.cancel()
                
            # Create new recurring timer (3 seconds to avoid rate limits)
            self.update_timer = ui.timer(3.0, self.update_chart_loop) 
            self.log("✅ Live Updates Started (3s interval).")
            
        except Exception as e:
            self.log(f"❌ CRITICAL ERROR in Backtest: {e}")
            print(f"CRITICAL ERROR: {e}")

    async def update_chart_loop(self):
        print("DEBUG: update_chart_loop tick") # Ultimate Debug
        if not self.is_running: return
        
        # Live Update Logic
        try:
            # self.log("debug: checking live price...") # Too noisy
            # Run blocking fetch in a separate thread to keep UI responsive
            latest_df = await asyncio.to_thread(fetch_raw_data, cfg.SYMBOL, cfg.TIMEFRAME, 2)
            
            if latest_df is not None and not latest_df.empty:
                last_row = latest_df.iloc[-1]
                candle = {
                    'time': int(last_row['timestamp'].timestamp()),
                    'open': last_row['open'],
                    'high': last_row['high'],
                    'low': last_row['low'],
                    'close': last_row['close']
                }
                
                # Send update to JS
                ui.run_javascript(f'window.updateCandleGlobal({json.dumps(candle)})')
                self.update_price_label(last_row['close'])
                
                # Debug Log (Show every update to confirm it's working)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Live Update: {last_row['close']} (TS: {candle['time']})")
                
            else:
                self.log("⚠️ Live Update: Fetch returned empty.")
                    
        except Exception as e:
            self.log(f"❌ Update Error: {e}")
            print(f"Update Error: {e}")
            pass

    def update_price_label(self, price):
        self.price_label.text = f'{price:,.2f} USDT'
        if len(self.history_data) > 1:
            prev = self.history_data[-2]['close']
            color = 'text-green-400' if price >= prev else 'text-red-400'
            self.price_label.classes(color, remove='text-green-400 text-red-400')

    def start_bot(self):
        self.is_running = True
        self.status_label.text = 'RUNNING'
        self.log("Bot Started.")
        if not self.history_data:
            self.run_backtest_simulation() # Load real data if empty

    def stop_bot(self):
        self.is_running = False
        self.status_label.text = 'STOPPED'
        self.log("Bot Stopped.")
    
    def log(self, msg):
        self.log_container.push(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

dashboard = TradingDashboard()
ui.run(title='Trading Bot Dashboard', dark=True, port=8080)
