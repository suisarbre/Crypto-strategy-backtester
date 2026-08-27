
# 2. Trading Target & Constraints
SYMBOL = 'BTC/USDT'
TIMEFRAME = '5m'
MAX_FETCH_LIMIT = 15000

# [Optimization] Strategy Search Space
AVAILABLE_STRATEGIES = ['standard'] 
ACTIVE_STRATEGY = 'standard'
AVAILABLE_TIMEFRAMES = ['5m'] 

# [Optimization] Performance Thresholds
PREVIOUS_BEST_SCORE = -999
TIMEFRAME_CHANGE_THRESHOLD = 0.10

# [Optimization] Constraints
OPTIMIZER_MIN_TRADES = 10    
OPTIMIZER_MAX_TRADES = 500    
OPTIMIZER_MAX_MDD = 0.3       

# [Strategy Defaults] (Legacy Support - ideally move to JSON)
EMA_FILTER_PERIOD = 80        
USE_ATR_SL = True             
ATR_TRAIL_SCAN_RANGE = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0] 
ATR_PERIOD = 14               
CHOP_THRESHOLD = 45.0         
ATR_TRAIL_MULTIPLIER = 7.0    
USE_HYBRID_EXIT = True        
HYBRID_EXIT_STRATEGY = 'SUPERTREND' 
SUPERTREND_FACTOR = 5.0       
COOLDOWN_CANDLES = 0          

# [Account & Risk]
FEE_RATE = 0.001              
START_BALANCE = 100.0         
KERNEL_LOOKBACK_MULT = 3      # Window = lookback * mult + lookback. Original: startAtBar=25 → ~33 bars      

# [Leverage & Risk Management]
# Fixed at 1x (ADR-003): binanceus is spot-only, so leveraged backtest results
# have no live counterpart, and leverage let the optimizer inflate its fitness
# score without improving the signal. The mechanism remains in the code —
# widening this range is all that's needed to reverse the decision.
LEVERAGE_TEST_RANGE = [1]
DEFAULT_LEVERAGE = 1
TP_RATIO = 0.99           
SL_RATIO = 0.030

# [Global Risk Control] (SRS REQ-RM-01, REQ-RM-02)
DAILY_LOSS_LIMIT = 0.05       # Pause if -5% daily drop
USE_TRAILING_STOP = True      # Centralized TS
TS_ACTIVATION = 0.02          # Start TS when +2% profit
TS_CALLBACK = 0.01            # Trail by 1%
USE_BREAKEVEN = True          # Centralized BE
BE_TRIGGER = 0.015            # Move to BE when +1.5% profit
BE_OFFSET = 0.002             # BE + 0.2% (to cover fees)          

# [Current Config] (Runtime State)
CURRENT_CONFIG = {
    'max_bars_back': 10000,
    'neighbors': 8,      
    'rsi_length': 14,      
    'wt_channel_len': 10,  
    'wt_avg_len': 11,       # Original LDC default: 11 (not 21)
    'cci_length': 20,      
    'adx_length': 20,       # Original LDC default: 20 (not 14)
    'adx_threshold': 20,    # Original LDC default: 20
    'rsi2_length': 9,        # 5th ML feature: RSI with shorter period
    'use_kernel': True,    
    'kernel_lookback': 8,   # Original LDC default: 8
    'kernel_weight': 8,     # Original LDC default: 8 (relative weight / alpha)
    'kernel_lookback_mult': KERNEL_LOOKBACK_MULT,  # Window = lookback * mult + lookback
   
    # Strategy filter params (referenced by strategies.json rules)
    'chop_threshold': CHOP_THRESHOLD,
    'ema_period': EMA_FILTER_PERIOD,
    'use_ema_filter': 0.0,
    'use_adx_filter': 0.0,
    'sl_multiplier': ATR_TRAIL_MULTIPLIER,

    # Regime Rider params (dual-EMA regime gate + RSI momentum filter)
    'ema_fast_period': 21,       # Fast EMA for trend confirmation (~1h45m on 5m)
    'ema_slow_period': 55,       # Slow EMA for macro trend (~4.5h on 5m)
    'rsi_momentum_gate': 48,     # Long entry: RSI must be above this (bullish bias)
    'rsi_counter_gate': 52,      # Short entry: RSI must be below this (bearish bias)

    'tp_ratio': TP_RATIO,      
    'sl_ratio': SL_RATIO,
    'leverage': DEFAULT_LEVERAGE
}

# [Modularization] Phase 1: Externalized Strategy Parameters
# Ranges based on jdehorty's KNN Lorentzian Classification deep research.
# Sweet spots validated on BTC/USDT 5m/15m crypto data.
STRATEGY_PARAMS = {
    "standard": {
        # ML Feature Indicator Lengths — tight around original defaults
        "rsi_length":     [9, 11, 14, 17, 21],         # F1: RSI (default 14)
        "wt_channel_len": [8, 9, 10, 11, 14],           # F2: WT channel (default 10)
        "wt_avg_len":     [9, 11, 13, 15],              # F2: WT average (default 11)
        "cci_length":     [14, 17, 20, 23, 26],         # F3: CCI (default 20)
        "adx_length":     [14, 17, 20, 23, 26],         # F4: ADX (default 20)
        "rsi2_length":    [5, 7, 9, 11, 14],            # F5: RSI short (default 9)

        # KNN Neighbors — sweet spot 6-16 for crypto (default 8)
        "neighbors": [6, 8, 10, 12, 16],

        # Filter Thresholds
        "adx_threshold":  [15, 20, 25, 30],             # Original default: 20
        "chop_threshold": [38.0, 45.0, 53.0, 60.0],     # Choppiness filter
        "ema_period":     [50, 80, 120, 160, 200],      # EMA trend filter
        "use_ema_filter": [0.0, 1.0],
        "use_adx_filter": [0.0, 1.0],

        # Risk Management
        "leverage": LEVERAGE_TEST_RANGE,
        "sl_multiplier": ATR_TRAIL_SCAN_RANGE if USE_ATR_SL else [0.0]
    },
    "regime_rider": {
        # ML Feature Indicator Lengths (same core as standard)
        "rsi_length":     [9, 11, 14, 17, 21],
        "wt_channel_len": [8, 9, 10, 11, 14],
        "wt_avg_len":     [9, 11, 13, 15],
        "cci_length":     [14, 17, 20, 23, 26],
        "adx_length":     [14, 17, 20, 23, 26],
        "rsi2_length":    [5, 7, 9, 11, 14],
        "neighbors":      [6, 8, 10, 12, 16],

        # Regime Gate — Dual EMA (trend alignment filter)
        "ema_fast_period": [13, 17, 21, 26, 34],
        "ema_slow_period": [34, 44, 55, 70, 89],

        # Regime Gate — RSI Momentum (dead zone filter)
        "rsi_momentum_gate": [40, 44, 48, 50],
        "rsi_counter_gate":  [50, 52, 56, 60],

        # Regime Gate — Trend Strength
        "adx_threshold":  [15, 20, 25, 30],
        "chop_threshold": [38.0, 42.0, 45.0, 50.0],

        # Risk Management
        "leverage": LEVERAGE_TEST_RANGE,
        "sl_multiplier": ATR_TRAIL_SCAN_RANGE if USE_ATR_SL else [0.0]
    }
}