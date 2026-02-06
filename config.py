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
EMA_FILTER_PERIOD = 200       # 추세 필터용 EMA 기간

# [ATR Dynamic Stop Loss]
USE_ATR_SL = True             # ATR 기반 손절 사용 여부 (False면 고정 SL_RATIO)
# [ATR Dynamic Trailing Stop]
USE_ATR_SL = True             # ATR 기반 익절/손절 최적화 사용 여부
ATR_TRAIL_SCAN_RANGE = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0] # [Long Trend] 더 길게 가져가기 위한 넓은 범위 설정
ATR_PERIOD = 14               # ATR 계산 기간 (기본 14)

# [NEW] Strategy Enhancements (Default Values)
CHOP_THRESHOLD = 61.8         # Choppiness Index 임계값
ATR_TRAIL_MULTIPLIER = 5.0    # 기본 Trailing Stop 배수 (수동/단일 실행용, 최적화 시 위 범위 사용)

# [Trading Parameters]
FEE_RATE = 0.001              # 거래 수수료 (0.1%)
START_BALANCE = 100.0         # 테스트 시작 잔고
KERNEL_LOOKBACK_MULT = 5      # 커널 룩백 배수 (lookback * mult)

# 3. 전략 기본 설정
LEVERAGE_TEST_RANGE = [1, 2, 3,4,5,6,7] # [Safety] 최적화 시 테스트할 레버리지 목록 (OOS 과적합 방지)
DEFAULT_LEVERAGE = 3      # 초기 레버리지 (안전하게 3배로 시작)
TP_RATIO = 0.99           # 익절 비율 (사용 안 함/로직 내부 처리)
SL_RATIO = 0.030          # 손절 비율 (3%)


# 4. 봇 시스템 설정
OPTIMIZE_INTERVAL_MINUTES = 240 # WFA 재최적화 주기 (4시간 권장)

# [WFA: Walk-Forward Analysis Settings]
WFA_ENABLED = True
WFA_WINDOW_SIZE = 15000       # 전체 롤링 윈도우 크기 (Safe OOS를 포함한 전체 데이터)
# IS(In-Sample) : OOS(Out-of-Sample) 비율 -> OOS는 검증용
WFA_TRAIN_RATIO = 0.7         # 10k(Train) : 5k(Test) 정도 비율 유지

# [Persistence]
PARAMS_FILE_PATH = "best_params.json" # 최적 파라미터 저장 경로


# 5. 기타 설정
CURRENT_CONFIG = {
    'max_bars_back': 10000,
    'neighbors': 11,      
    'rsi_length': 14,      
    'wt_channel_len': 10,  
    'wt_avg_len': 21,      
    'cci_length': 20,      
    'adx_length': 14,      
    'adx_threshold': 20,  
    'use_kernel': True,    
    'kernel_lookback': 15,  
    'kernel_weight': 8,    
   
    'tp_ratio': TP_RATIO,      
    'sl_ratio': SL_RATIO,
    'leverage': DEFAULT_LEVERAGE
}

