try:
    from secret_keys import API_KEY, SECRET_KEY
except ImportError:
    print("⚠️ [WARNING] secret_keys.py not found. Using dummy keys.")
    API_KEY = ''
    SECRET_KEY = ''
# 2. 거래 대상 설정
# 2. 거래 대상 설정
SYMBOL = 'BTC/USDT'
# [Multi-Strategy] 사용할 전략 목록 (최적화 시 모두 테스트됨)
AVAILABLE_STRATEGIES = ['standard'] #standard aggressive
# 현재 활성화된 전략 (기본값, 최적화 후 자동 변경될 수 있음)
ACTIVE_STRATEGY = 'standard'

# [Multi-Timeframe] 최적화 대상 타임프레임 목록
AVAILABLE_TIMEFRAMES = ['5m'] 
# 현재 활성화된 타임프레임 (기본값)
TIMEFRAME = '5m'
MAX_FETCH_LIMIT = 15000

# [Optimization] 이전 최적화 최고 점수 (타임프레임 변경 조건 확인용)
PREVIOUS_BEST_SCORE = -999
# [Optimization] 타임프레임 변경을 위한 최소 점수 향상율 (0.1 = 10%)
TIMEFRAME_CHANGE_THRESHOLD = 0.10

# [Optimization Filters]
OPTIMIZER_MIN_TRADES = 30     # 최소 거래 횟수 (과적합 방지, 10 -> 30 상향)
OPTIMIZER_MAX_TRADES = 500    # [New] 최대 거래 횟수 (과도한 스캘핑 방지)
OPTIMIZER_MAX_MDD = 0.3       # 최대 허용 MDD (30%)
EMA_FILTER_PERIOD = 80        # [Tuned] 추세 필터 (200 -> 80) 더 빠른 진입
USE_ATR_SL = True             # ATR 기반 손절 사용 여부
ATR_TRAIL_SCAN_RANGE = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0] 
ATR_PERIOD = 14               

# [NEW] Strategy Enhancements (Default Values)
CHOP_THRESHOLD = 45.0         # [Stricter] 횡보 필터 강화 (50.0 -> 45.0)
ATR_TRAIL_MULTIPLIER = 7.0    # [Looser] Trailing Stop (6.0 -> 7.0) 길게 먹기
USE_HYBRID_EXIT = True        
HYBRID_EXIT_STRATEGY = 'SUPERTREND' 
SUPERTREND_FACTOR = 5.0       # [Widened] 추세 길게 타기 (4.0 -> 5.0)

# [New] Cooldown Settings
COOLDOWN_CANDLES = 0          # [Tuned] 쿨다운 제거 (기회 놓치지 않기)

# [Trading Parameters]
FEE_RATE = 0.001              
START_BALANCE = 100.0         
KERNEL_LOOKBACK_MULT = 5      

# 3. 전략 기본 설정
LEVERAGE_TEST_RANGE = [1, 2, 3,4,5,6,7] 
DEFAULT_LEVERAGE = 3      
TP_RATIO = 0.99           
SL_RATIO = 0.030          


# 4. 봇 시스템 설정
OPTIMIZE_INTERVAL_MINUTES = 240 

# [WFA: Walk-Forward Analysis Settings]
WFA_ENABLED = True
WFA_WINDOW_SIZE = 15000       
WFA_TRAIN_RATIO = 0.7         

# [Persistence]
PARAMS_FILE_PATH = "best_params.json" 


# 5. 기타 설정
CURRENT_CONFIG = {
    'max_bars_back': 10000,
    'neighbors': 8,       # [Tuned] 민감도 상향 (11 -> 8)
    'rsi_length': 14,      
    'wt_channel_len': 10,  
    'wt_avg_len': 21,      
    'cci_length': 20,      
    'adx_length': 14,      
    'adx_threshold': 15,  # [Tuned] 추세 강도 문턱 낮춤 (20 -> 15)
    'use_kernel': True,    
    'kernel_lookback': 15,  
    'kernel_weight': 8,    
   
    'tp_ratio': TP_RATIO,      
    'sl_ratio': SL_RATIO,
    'leverage': DEFAULT_LEVERAGE
}

