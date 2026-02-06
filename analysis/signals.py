import numpy as np
import config as cfg
from sklearn.neighbors import KNeighborsClassifier

# ⚠️ 중요: 아래 줄에 'def generate_signals(...):'가 반드시 있어야 합니다.
def generate_signals(df, conf):
    # 데이터프레임 복사 (원본 보존)
    df = df.copy()

    # 타겟 설정 (다음 봉 종가가 오르면 1, 내리면 -1)
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, -1)
    
    # [Lorentzian Features] 사용할 피처 컬럼 (RSI, WT, CCI, ADX)
    feature_cols = ['rsi', 'wt1', 'cci', 'adx']
    
    # 데이터가 비어있지 않은지 확인
    if df[feature_cols].isnull().values.any():
        df = df.dropna()
        
    X = df[feature_cols].values
    y = df['target'].values
    
    # 학습 데이터 (마지막 캔들은 정답(미래)을 모르므로 학습에서 제외)
    X_train = X[:-1]
    y_train = y[:-1]
    
    # [C++ Integration] Try to use native engine if available
    try:
        import cpp_engine
        use_cpp = True
    except ImportError:
        use_cpp = False
        
    # 설정값 가져오기 (없으면 기본값 사용)
    neighbors = int(conf.get('neighbors', 8))
    
    # KNN 모델 학습 및 예측
    try:
        if use_cpp:
            # C++ FastKNN 사용
            knn = cpp_engine.FastKNN(neighbors)
            knn.fit(X_train, y_train.astype(np.int32))
            df['pred_signal'] = knn.predict(X.astype(np.float64))
        else:
            # Python Scikit-Learn 사용 (Fallback)
            knn = KNeighborsClassifier(n_neighbors=neighbors, metric='manhattan')
            knn.fit(X_train, y_train)
            df['pred_signal'] = knn.predict(X)
            
    except Exception as e:
        print(f"KNN Error (Cpp={use_cpp}): {e}")
        df['pred_signal'] = 0
    
    # [Trend Filter] EMA 200
    ema_period = int(conf.get('ema_period', 200))
    df['ema'] = df['close'].ewm(span=ema_period, adjust=False).mean()
    
    # [NEW] Choppiness Filter
    # 횡보장(수치 높음)이면 진입 금지 (Shield)
    chop_thresh = getattr(cfg, 'CHOP_THRESHOLD', 61.8)
    chop_cond = df['chop'] < chop_thresh
    
    # [NEW] SuperTrend Filter
    # Trend Spear: 대추세와 방향이 맞을 때만 진입
    st_long = df['supertrend_trend'] == 1
    st_short = df['supertrend_trend'] == -1
    
    # 매매 조건 결합 (Signals + ADX + EMA + CHOP + SuperTrend)
    long_cond = (
        (df['pred_signal'] == 1) &
        (df['adx'] > conf['adx_threshold']) &
        (df['close'] > df['ema']) &
        (chop_cond) & # [NEW]
        (st_long)     # [NEW]
    )
    
    short_cond = (
        (df['pred_signal'] == -1) &
        (df['adx'] > conf['adx_threshold']) &
        (df['close'] < df['ema']) &
        (chop_cond) & # [NEW]
        (st_short)    # [NEW]
    )
    
    # 최종 신호 (1: 롱, -1: 숏, 0: 대기)
    df['final_signal'] = np.where(long_cond, 1, np.where(short_cond, -1, 0))
    
    return df