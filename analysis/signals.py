# [LEGACY] This module is kept for backward compatibility with JsonStrategyLogic.
# New Python strategies should implement their own signal generation.
import config as cfg
import numpy as np
from sklearn.neighbors import KNeighborsClassifier

def generate_signals(df, conf, strategy_json=None):
    """Run KNN prediction + strategy rule evaluation to produce final signals."""
    df = df.copy()

    # Target: next candle close up → 1, down → -1
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, -1)
    
    # Lorentzian feature columns (RSI, WT, CCI, ADX)
    feature_cols = ['rsi', 'wt1', 'cci', 'adx']
    
    if df[feature_cols].isnull().values.any():
        df = df.dropna()
        
    X = df[feature_cols].values
    y = df['target'].values
    
    # Train on all but last bar (last bar's target is unknown/future)
    X_train = X[:-1]
    y_train = y[:-1]
    
    import os
    # [C++ Integration] Try to use native engine if available
    try:
        if os.environ.get('DISABLE_CPP', '0') == '1':
             raise ImportError("Disabled via env")
             
        import cpp_engine
        use_cpp = True
    except ImportError:
        use_cpp = False
        
    neighbors = int(conf.get('neighbors', 8))
    
    # KNN training & prediction
    try:
        if use_cpp:
            knn = cpp_engine.FastKNN(neighbors)
            knn.fit(X_train, y_train.astype(np.int32))
            df['pred_signal'] = knn.predict(X.astype(np.float64))
        else:
            # Python scikit-learn fallback
            knn = KNeighborsClassifier(n_neighbors=neighbors, metric='manhattan')
            knn.fit(X_train, y_train)
            df['pred_signal'] = knn.predict(X)
            
    except Exception as e:
        print(f"KNN Error (Cpp={use_cpp}): {e}")
        df['pred_signal'] = 0
    
    # [Strategies.json] Load Strategy
    # TODO: Pass strategy path or json content in conf? For now, load from default path.
    import os
    from analysis.signal_evaluator import SignalEvaluator

    strat_json = ""
    if strategy_json:
        # If argument provided, use it
        strat_json = strategy_json
    else:
        # Fallback to default path
        strat_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'strategies.json')
        if os.path.exists(strat_path):
            with open(strat_path, 'r') as f:
                strat_json = f.read()
            
    if not strat_json:
        print(f"Warning: strategies.json not found or empty. no signals.")
        df['final_signal'] = 0
        df['exit_signal'] = 0
    else:
        # [Dynamic Indicators]
        from analysis.indicators import add_dynamic_indicators
        df = add_dynamic_indicators(df, strat_json, config=conf)
        
        evaluator = SignalEvaluator(strat_json)
        
        # Ensure we have required columns for evaluator even if not in feature_cols
        if 'kernel_rising' in df.columns and 'kernel_falling' in df.columns:
            df['kernel_ls'] = np.where(df['kernel_rising'], 1, np.where(df['kernel_falling'], -1, 0))
        
        if 'ema_filter' not in df.columns:
            if 'ema' in df.columns:
                df['ema_filter'] = df['ema']
            elif 'ema_200' in df.columns:
                 df['ema_filter'] = df['ema_200']
        
        df['final_signal'] = evaluator.evaluate(df, conf)
        df['exit_signal'] = evaluator.evaluate_exit(df, conf) # [NEW]
    
    return df