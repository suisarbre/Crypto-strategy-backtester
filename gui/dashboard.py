import os
import sys
import json
import asyncio
import random
import time
import mimetypes
from datetime import datetime
import pandas as pd

# NiceGUI & Config
from nicegui import ui, app
import config as cfg

# Local Modules
# [Path Fix] Add parent directory to path to allow imports from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.data_loader import fetch_raw_data
from analysis.indicators import add_indicators
from analysis.signals import generate_signals

# ==============================================================================
# 1. System Configuration
# ==============================================================================

# [Windows Fix] Force JS MIME type (sometimes defaults to text/plain)
mimetypes.add_type('application/javascript', '.js')

# Serve static files with ABSOLUTE path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app.add_static_files('/static', STATIC_DIR)

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

# ==============================================================================
# 2. Custom Components
# ==============================================================================

class ChartElement(ui.element):
    """
    Custom NiceGUI Element for Lightweight Charts.
    Wraps the JS library commands to separate Python logic from JS execution.
    """
    def __init__(self):
        super().__init__('div')
        # [CRITICAL] Force DOM ID so document.getElementById works
        self.props(f'id={self.id}') 
        self.classes('w-full h-full')
        self.style('min-height: 400px; background-color: #111;')
        self.on('init', self.init_chart)

    def init_chart(self, e=None):
        # Trigger global JS function to bind chart to this div ID
        ui.run_javascript(f'window.initChart("{self.id}")')

    def set_data(self, data):
        ui.run_javascript(f'window.setChartData("{self.id}", {json.dumps(data)})')

    def update_candle(self, candle):
        ui.run_javascript(f'window.updateChart("{self.id}", {json.dumps(candle)})')
    
    def set_markers(self, markers):
        ui.run_javascript(f'window.setMarkers("{self.id}", {json.dumps(markers)})')

# ==============================================================================
# 3. Main Dashboard Class
# ==============================================================================

class StreamRedirector:
    """Redirects sys.stdout/stderr to both console and a callback."""
    def __init__(self, stream, callback, quiet=False):
        self.stream = stream
        self.callback = callback
        self.quiet = quiet
        self.encoding = getattr(stream, 'encoding', 'utf-8')

    def write(self, message):
        # 1. Console Output (Optional)
        if not self.quiet:
            self.stream.write(message)
            self.stream.flush()

        # 2. Callback (Filtered)
        if message:
            self.callback(message)

    def flush(self):
        self.stream.flush()
        
    def isatty(self):
        return getattr(self.stream, 'isatty', lambda: False)()

class TradingDashboard:
    def __init__(self):
        self.is_running = False
        self.client_connected = False
        self.history_data = [] 
        self.chart = None
        self.bot = None
        
        # Ensure data directory exists
        if not os.path.exists('chart_data'):
            os.makedirs('chart_data')

        # [Log Redirection] Hook stdout/stderr
        # Prevent recursive wrapping on reload
        if not isinstance(sys.stdout, StreamRedirector):
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            # stdout -> Quiet (Web UI Only)
            sys.stdout = StreamRedirector(sys.stdout, self._handle_stream_message, quiet=True)
            # stderr -> Loud (Console + Web UI for errors)
            sys.stderr = StreamRedirector(sys.stderr, self._handle_stream_message, quiet=False)
        else:
            # Already wrapped, just ensure callbacks are up to date if instance changed?
            # Since 'self' is new, we might need to update the callback method bound to the *old* redirector?
            # Actually, sys.stdout persists across reloads? NiceGUI reloads the module.
            # Behavior: New Dashboard instance created. Old Redirector points to OLD Dashboard instance's _handle_stream_message.
            # Old Dashboard instance is dead.
            # WE MUST UPDATE THE CALLBACK.
            sys.stdout.callback = self._handle_stream_message
            sys.stderr.callback = self._handle_stream_message

    def _handle_stream_message(self, msg):
        """Filters and pushes terminal logs to the Web UI."""
        # [Filter 1] Empty/Whitespace (Prevent spamming empty lines)
        if not msg.strip(): return
        
        # [Filter 2] User Request: Hide "Candle Close" heartbeat
        if "Candle Close" in msg: return
        
        # [Filter 3] Console Progress/Status Bars (starts with \r)
        # simplistic check: if it looks like a progress update, skip it
        if msg.startswith('\r'): return
        
        # Push to UI if client connected
        if getattr(self, 'client_connected', False):
            try:
                if hasattr(self, 'log_container') and self.log_container:
                     self.log_container.push(msg.strip())
            except Exception: pass

    # --------------------------------------------------------------------------
    # Lifecycle Methods
    # --------------------------------------------------------------------------

    def set_bot(self, bot):
        """Called by main.py to attach the bot instance."""
        self.bot = bot
        self.log("✅ Bot Instance Attached")
        
        # Init internal state for trading loop
        self.interval_minutes = 5
        self.next_candle_time = 0
        self._sync_timeframe_state()
        
        # Start Background Task (Independent of UI)
        # MUST use create_task to avoid blocking startup (since loop is infinite)
        app.on_startup(lambda: asyncio.create_task(self.run_background_loop()))

    async def on_page_load(self):
        """Called via timer after the page is rendered for a client."""
        # [Singleton Guard] Prevent zombie tasks from updating current UI
        try:
            if not hasattr(self, 'log_container') or self.log_container.client.id != ui.context.client.id:
                return # Ignore stale tasks

            self.client_connected = True
            
            # Revert to direct await now that main loop blocking is fixed
            await asyncio.sleep(0.5)
            await self.init_chart()
            
        except Exception as e:
            print(f"Error in on_page_load: {e}")

    async def run_background_loop(self):
        """Background Task for Trading Logic (Runs forever)."""
        while True:
            try:
                if self.is_running:
                    self._trading_loop()
            except Exception as e:
                 # Print error (will go to UI via redirector)
                print(f"Background Loop Error: {e}")
            await asyncio.sleep(1.0)

    # --------------------------------------------------------------------------
    # UI Construction
    # --------------------------------------------------------------------------

    def build_ui(self):
        """Constructs the NiceGUI layout."""
        # A. Inject JavaScript
        self._inject_javascript()

        # B. Header
        with ui.header().classes('row items-center') as header:
            header.style(f'background-color: {THEME["dark"]}')
            ui.icon('show_chart', size='32px').classes('text-white')
            ui.label('TRADING BOT DASHBOARD').classes('text-h6 text-white font-bold ml-2')
            
            ui.space()
            self.balance_label = ui.label('Bal: $100 (0.00%)').classes('text-h6 text-gray-300 mr-6 font-mono font-bold')
            self.price_label = ui.label('0.00 USDT').classes('text-h6 text-white mr-8 font-mono font-bold')
            self.status_label = ui.label('STOPPED').classes('text-red-500 font-bold mr-4 border border-red-500 px-2 rounded')

        # C. Sidebar
        with ui.left_drawer(value=True).classes('bg-gray-100') as drawer:
            ui.label('CONTROLS').classes('text-h6 font-bold m-4 text-gray-700')
            with ui.column().classes('w-full px-4 gap-4'):
                self.btn_start = ui.button('START', on_click=self.start_bot).props('push color=positive icon=play_arrow').classes('w-full h-12')
                self.btn_stop = ui.button('STOP', on_click=self.stop_bot).props('push color=negative icon=stop').classes('w-full h-12')
                
                ui.separator().classes('my-4')
                ui.label('ACTIONS').classes('text-caption font-bold text-gray-500')
                
                self.btn_optimize = ui.button('OPTIMIZE NOW', on_click=self.run_manual_optimization).classes('w-full bg-blue-600 text-white')
                self.btn_manual_close = ui.button('MANUAL CLOSE', on_click=self.trigger_manual_close).classes('w-full bg-orange-500 text-white')
                self.btn_kill = ui.button('KILL SWITCH', on_click=self.trigger_kill_switch).classes('w-full bg-red-700 text-white font-bold')
                
                ui.separator().classes('my-4')
                ui.button('SHOW DATA & STRATEGY', on_click=self.run_backtest_simulation).classes('w-full bg-purple-600 text-white font-bold')
                ui.button('RELOAD CHART', on_click=self.init_chart).classes('w-full bg-gray-500 text-white')
                ui.button('FORCE INIT JS', on_click=lambda: self.chart.init_chart()).classes('w-full bg-yellow-600 text-white')

        # D. Main Content
        with ui.column().classes('w-full h-[calc(100vh-64px)] p-4 bg-gray-900 no-wrap'):
            # Chart Area
            with ui.card().classes('w-full flex-grow bg-black border-gray-700 p-0 overflow-hidden relative'):
                 self.chart = ChartElement()

            # Log Area
            with ui.card().classes('w-full h-48 mt-4 bg-gray-800 text-white scroll-y-auto'):
                ui.label('LOGS').classes('text-xs font-bold text-gray-400 sticky top-0 bg-gray-800 p-1 block w-full')
                self.log_container = ui.log().classes('w-full font-mono text-sm p-2')
        
        # Start Status Update Loop (Per Client)
        self.update_status_continuously()

    def _inject_javascript(self):
        """Injects the Chart.js library and wrapper functions."""
        ui.add_head_html('''
        <script src="/static/lightweight-charts.js?v=2"></script>
        <script>
            // Global Helper to Init Chart on a specific container ID
            window.initChart = function(id) {
                const container = document.getElementById(id);
                if (!container) return;

                // UI Feedback
                container.innerText = "⏳ Init Chart...";
                container.style.color = "#888"; 
                // Center text
                container.style.display = "flex"; container.style.justifyContent = "center"; container.style.alignItems = "center";

                // Retry Loop for Library
                let attempts = 0;
                const check = setInterval(() => {
                    attempts++;
                    if (window.LightweightCharts) {
                        clearInterval(check);
                        container.innerText = ""; // Clear loader
                        container.style.display = "block"; // Reset Display
                        createChartInstance(container);
                    } else if (attempts > 50) {
                        clearInterval(check);
                        container.innerText = "❌ Chart Lib Error";
                        container.style.color = "red";
                    }
                }, 100);
            };

            function createChartInstance(container) {
                if (container.chart) return; // Already init

                const width = container.clientWidth;
                const height = container.clientHeight;
                
                // [Autofix] If size is 0, force default size
                if (width === 0 || height === 0) {
                    alert("⚠️ Chart detected 0x0 size. Forcing default size.");
                    container.style.width = '100%';
                    container.style.height = '500px';
                }

                try {
                    const chart = LightweightCharts.createChart(container, {
                        width: width || 800, 
                        height: height || 500,
                        layout: { textColor: '#d1d4dc', background: { type: 'solid', color: '#111111' } },
                        grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
                        timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#485c7b' },
                        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                    });

                    const series = chart.addCandlestickSeries({
                        upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
                    });
                    
                    // Auto Resize Observer
                    new ResizeObserver(entries => {
                        if (entries.length === 0 || entries[0].target !== container) return;
                        const newRect = entries[0].contentRect;
                        chart.applyOptions({ height: newRect.height, width: newRect.width });
                    }).observe(container);

                    // Store on DOM
                    container.chart = chart;
                    container.series = series;
                    
                } catch (e) {
                    container.innerText = "❌ JS Crash: " + e.message;
                    console.error(e);
                }
            }

            // Data Helpers
            window.setChartData = function(id, data) {
                 const c = document.getElementById(id);
                 if (c && c.series) {
                     c.series.setData(data);
                     c.chart.timeScale().fitContent();
                 }
            };

            window.updateChart = function(id, candle) {
                const c = document.getElementById(id);
                if (c && c.series) c.series.update(candle);
            };
            
            window.setMarkers = function(id, markers) {
                const c = document.getElementById(id);
                if (c && c.series) c.series.setMarkers(markers);
            };
        </script>
        ''')

    # --------------------------------------------------------------------------
    # Chart Control Methods
    # --------------------------------------------------------------------------

    async def init_chart(self):
        """Called when page is ready. Triggers JS initialization."""
        if self.chart:
            self.chart.init_chart()
        self.log("✅ Chart Component Mounted.")
        # Auto-load data after small delay
        ui.timer(1.0, self.run_backtest_simulation, once=True)

    async def run_backtest_simulation(self):
        """Fetches data, runs strategy, updates chart (Async to prevent blocking)."""
        try:
            limit = cfg.MAX_FETCH_LIMIT  # [User Request] Load full history (15k)
            self.log(f"Loading Data for {cfg.SYMBOL} ({cfg.TIMEFRAME})...")
            
            # [Optimization] Run Heavy Database/Network/Math in Thread
            def _heavy_loader():
                # 1. Fetch & Cache
                df = self.fetch_and_cache_data(cfg.SYMBOL, cfg.TIMEFRAME, limit)
                if df is None or df.empty: return None, None, None
                
                if len(df) > limit:
                    df = df.tail(limit).copy().reset_index(drop=True)

                # 2. Strategy
                if self.bot:
                    config = self.bot.state.config.copy()
                else:
                    config = cfg.CURRENT_CONFIG.copy()
                    
                df = add_indicators(df, config)
                df = generate_signals(df, config)
                
                # 3. Markers
                from core.backtester import run_backtest_with_markers
                markers = run_backtest_with_markers(df, config)
                
                return df, markers, config

            # Await Thread Result
            self.log("⏳ Processing Data (Threaded)...")
            df, markers, _ = await asyncio.to_thread(_heavy_loader)
            
            if df is None:
                self.log("❌ Error: Failed to fetch data.")
                return

            self.log(f"🤖 Config Used. Processing {len(df)} bars...")

            # 4. Prepare Chart Data & Sanitize
            def clean_float(x):
                if isinstance(x, float):
                    if x != x or x == float('inf') or x == float('-inf'): return None
                return x

            chart_data = []
            for idx, row in df.iterrows():
                ts = int(row['timestamp'].timestamp())
                chart_data.append({
                    'time': ts, 
                    'open': clean_float(row['open']), 
                    'high': clean_float(row['high']), 
                    'low': clean_float(row['low']), 
                    'close': clean_float(row['close'])
                })

            # Sanitize Markers
            cleaned_markers = []
            if markers:
                for m in markers:
                    cleaned_markers.append(m.copy())
            self.chart_markers = cleaned_markers

            # 5. Push to Chart
            if self.chart:
                try:
                    # Chunked update if data is huge? Lightweight charts handles 15k fine usually.
                    self.chart.set_data(chart_data)
                    
                    if self.chart_markers:
                        self.chart.set_markers(self.chart_markers)
                        self.log(f"✅ Markers Sent: {len(self.chart_markers)}")
                except RuntimeError:
                    self.log("⚠️ Chart update skipped (Client disconnected)")
                    return
            
            # 6. Update State
            self.history_data = chart_data
            self.current_price = chart_data[-1]['close'] if chart_data else 0
            self.update_price_label(self.current_price)
            
            # 7. Start Live Updates
            # self.is_running = True # [Fix] Do NOT auto-start trading. Wait for user.
            if hasattr(self, 'update_timer') and self.update_timer:
                self.update_timer.cancel()
            self.update_timer = ui.timer(10.0, self.update_chart_loop)
            self.log("✅ Live Chart Updates Started (Trading Paused).")
            
            # 8. Auto-Start Optimization (Once)
            if self.bot and not getattr(self, 'initial_optimization_done', False):
                self.initial_optimization_done = True
                asyncio.create_task(self._run_initial_optimization())

        except Exception as e:
            self.log(f"❌ Simulation Error: {e}")
            import traceback
            traceback.print_exc()

    def _simulate_trades_and_markers(self, df, config):
        """Deprecated: Use core.backtester.run_backtest_with_markers instead."""
        pass

    async def update_chart_loop(self):
        """Recurring task to fetch latest data, calc signals, and update chart."""
        # [Fix] Run chart updates regardless of Trading State (Observation Mode)
        # if not self.is_running: return
        
        # [Concurrency Guard] Skip if previous update is still running
        if getattr(self, 'is_updating_chart', False):
            return
            
        try:
            self.is_updating_chart = True # [Fix] Set Guard
            current_time = time.time()
            
            # Use fixed window for live updates (enough for indicators)
            fetch_limit = 300 
            
            # Fetch Data
            latest_df = await asyncio.to_thread(fetch_raw_data, cfg.SYMBOL, cfg.TIMEFRAME, fetch_limit)
            
            if latest_df is not None and not latest_df.empty:
                # [Sanitization] Prevent NaN/Inf from breaking JSON serialization
                def clean_float(x):
                    if isinstance(x, float):
                        if x != x: return None # NaN
                        if x == float('inf') or x == float('-inf'): return None
                    return x

                # 1. Update Price (Last Candle)
                last_row = latest_df.iloc[-1]
                candle = {
                    'time': int(last_row['timestamp'].timestamp()),
                    'open': clean_float(last_row['open']), 
                    'high': clean_float(last_row['high']), 
                    'low': clean_float(last_row['low']), 
                    'close': clean_float(last_row['close'])
                }
                if self.chart:
                    try:
                        self.chart.update_candle(candle)
                    except RuntimeError: pass
                
                # 2. Update Balance (Real-time)
                self.update_price_label(last_row['close'])
                
                # 3. Update Markers (Real-time)
                # Apply current strategy config
                if self.bot:
                    config = self.bot.state.config.copy()
                else:
                    config = cfg.CURRENT_CONFIG.copy()
                
                # [Optimization] Run heavy calc in thread
                def _calc_logic(df, cfg_):
                    from core.backtester import run_backtest_with_markers
                    # Calc Indicators & Signals
                    df = add_indicators(df, cfg_)
                    df = generate_signals(df, cfg_)
                    # Generate Markers (Warmup=50 to allow indicators to stabilize)
                    return run_backtest_with_markers(df, cfg_, warmup=50)

                new_chunk_markers = await asyncio.to_thread(_calc_logic, latest_df, config)
                
                # Sanitize Markers
                cleaned_markers = []
                for m in new_chunk_markers:
                    cleaned_m = m.copy()
                    cleaned_markers.append(cleaned_m)
                
                new_chunk_markers = cleaned_markers
                
                # [Smart Merge Fix] 
                # Instead of additive merge, we MUST replace the Time Window.
                # This clears "Phantom Entries" that disappear when the simulation window moves.
                if not hasattr(self, 'chart_markers'): self.chart_markers = []
                
                if not latest_df.empty:
                    min_ts = int(latest_df['timestamp'].iloc[0].timestamp())
                    max_ts = int(latest_df['timestamp'].iloc[-1].timestamp())
                    
                    # 1. Keep markers OUTSIDE the new window
                    kept_markers = [m for m in self.chart_markers if m['time'] < min_ts or m['time'] > max_ts]
                    
                    # 2. Add VALID markers from the new simulation
                    kept_markers.extend(new_chunk_markers)
                    
                    # 3. Sort & Assign
                    self.chart_markers = sorted(kept_markers, key=lambda x: x['time'])
                    
                    if self.chart:
                        try:
                            self.chart.set_markers(self.chart_markers)
                            # log removed to prevent spam every 10s
                        except RuntimeError: pass
                        
        except Exception as e:
            print(f"Update Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_updating_chart = False

    # --------------------------------------------------------------------------
    # Utility Methods
    # --------------------------------------------------------------------------

    def fetch_and_cache_data(self, symbol, timeframe, limit=5000):
        """Loads CSV cache, fetches missing data, and saves back to CSV."""
        safe_symbol = symbol.replace('/', '_')
        file_path = f"chart_data/{safe_symbol}_{timeframe}.csv"
        existing_df = pd.DataFrame()
        
        # Load Cache
        if os.path.exists(file_path):
            try:
                existing_df = pd.read_csv(file_path)
                existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
            except Exception: pass
        
        # Fetch New
        if existing_df.empty:
             new_df = fetch_raw_data(symbol, timeframe, limit)
        else:
             new_df = fetch_raw_data(symbol, timeframe, max(100, limit))
        
        if new_df is None or new_df.empty:
            return existing_df
            
        # Merge
        if not existing_df.empty:
            combined = pd.concat([existing_df, new_df])
            combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
            combined = combined.sort_values(by='timestamp').reset_index(drop=True)
            final_df = combined
        else:
            final_df = new_df
            
        # Save
        try:
            final_df.to_csv(file_path, index=False)
        except Exception: pass
            
        return final_df

    def log(self, msg):
        """Safe logger. Prints to console, which is redirected to UI."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        # This print will be caught by StreamRedirector and sent to self.log_container
        print(f"[{timestamp}] {msg}")

    # --------------------------------------------------------------------------
    # Bot Control Wrappers
    # --------------------------------------------------------------------------

    def start_bot(self):
        self.is_running = True
        if self.bot: self.bot.resume_trading()
        self.log("▶️ Bot Resumed")

    def stop_bot(self):
        self.is_running = False
        if self.bot: self.bot.kill_switch()
        self.log("⏹️ Bot Stopped")

    def run_manual_optimization(self):
        if self.bot:
            self.log("🚀 Starting Manual Optimization...")
            asyncio.create_task(asyncio.to_thread(self.bot.run_optimization_thread))
        else:
            self.log("⚠️ No Bot Attached")

    def trigger_manual_close(self):
        if self.bot:
            self.bot.manual_close()
            self.log("👋 Manual Close Triggered")

    def trigger_kill_switch(self):
        if self.bot:
            self.bot.kill_switch()
            self.log("☠️ Kill Switch Triggered!")

    async def _run_initial_optimization(self):
        try:
            self.log("🤖 Auto-Starting Initial Optimization (Please Wait)...")
            self.btn_start.disable()
            
            # Start Optimization (Non-blocking trigger)
            self.bot.run_optimization_thread()
            
            # Wait for completion (Poll status)
            while getattr(self.bot, 'is_optimizing', False):
                await asyncio.sleep(1.0)
                
            self.log("✅ Initial Optimization Complete. Updating Chart...")
            
            # Refresh Chart with new Optimized Params
            await self.run_backtest_simulation()
            
        except Exception as e:
            self.log(f"❌ Optimization Failed: {e}")
        finally:
            self.btn_start.enable()

    def update_price_label(self, price):
        self.price_label.text = f'{price:,.2f} USDT'
        if len(self.history_data) > 1:
            prev = self.history_data[-2]['close']
            color = 'text-green-400' if price >= prev else 'text-red-400'
            self.price_label.classes(color, remove='text-green-400 text-red-400')
            
        # Update Balance Label
        if self.bot:
            bal = self.bot.state.balance
            start_bal = getattr(cfg, 'START_BALANCE', 100.0)
            roi = ((bal - start_bal) / start_bal) * 100
            
            sign = "+" if roi >= 0 else ""
            self.balance_label.text = f"${bal:,.2f} ({sign}{roi:.2f}%)"
            
            roi_color = 'text-green-400' if roi >= 0 else 'text-red-400'
            self.balance_label.classes(roi_color, remove='text-green-400 text-red-400 text-gray-300')

    def start_status_update_loop(self):
        ui.timer(1.0, self._sync_status)
        
    def update_status_continuously(self): # Legacy Alias
        self.start_status_update_loop()

    def _sync_status(self):
        if not self.bot: return
        
        # [Fix] Priority 1: Dashboard Execution State
        # If the dashboard loop is not running, the bot is effectively stopped.
        if not self.is_running:
             self.status_label.text = "STOPPED"
             self.status_label.classes('text-red-500', remove='text-green-500 text-yellow-500')
             return

        # Priority 2: Bot Internal State
        if self.bot.state.is_manual_stop:
            self.status_label.text = "KILLED"
            self.status_label.classes('text-red-500', remove='text-green-500 text-yellow-500')
        elif self.bot.state.is_paused:
            self.status_label.text = "PAUSED"
            self.status_label.classes('text-yellow-500', remove='text-green-500 text-red-500')
        else:
            self.status_label.text = "RUNNING"
            self.status_label.classes('text-green-500', remove='text-yellow-500 text-red-500')
            
    def _sync_timeframe_state(self):
        if not self.bot: return
        active_tf = self.bot.state.get_active_timeframe()
        # Note: Imports inside method to avoid circular dependency if utils imports dashboard
        from utils import parse_timeframe_to_minutes, get_next_candle_time
        
        minutes = parse_timeframe_to_minutes(active_tf)
        if minutes != self.interval_minutes or self.next_candle_time == 0:
            self.interval_minutes = minutes
            self.next_candle_time = get_next_candle_time(self.interval_minutes)

    def _trading_loop(self):
        if not self.bot: return
        if not self.is_running: return

        active_tf = self.bot.state.get_active_timeframe()
        from utils import parse_timeframe_to_minutes
        
        active_minutes = parse_timeframe_to_minutes(active_tf)
        if active_minutes != self.interval_minutes:
            self.log(f"🔄 Timeframe Changed: {active_tf}")
            self._sync_timeframe_state()
            
        now = datetime.now().timestamp()
        if now >= self.next_candle_time:
            self.log("⚡ Executing Trade Job...")
            try:
                self.bot.trade_job()
            except Exception as e:
                self.log(f"❌ Trade Job Error: {e}")
            self.next_candle_time += (self.interval_minutes * 60)
            
        import schedule
        schedule.run_pending()


# ==============================================================================
# 4. Entry Point & Instance
# ==============================================================================

dashboard = TradingDashboard()

@ui.page('/')
async def index():
    # Build the UI for this specific client connection
    dashboard.build_ui()
    
    # Schedule post-load tasks (Chart init)
    ui.timer(0.1, dashboard.on_page_load, once=True)

if __name__ == "__main__":
    ui.run(title='Trading Bot Dashboard', dark=True, port=8080)
