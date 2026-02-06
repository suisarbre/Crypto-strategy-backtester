import numpy as np
import config as cfg
from core.trade_state import TradeStateManager

def run_deep_backtest(df, config):
    """
    TradeStateManager를 사용한 백테스팅 함수 (C++ 가속 지원)
    """
    # [C++ Integration]
    try:
        import cpp_engine
        use_cpp = True
    except ImportError:
        use_cpp = False

    if use_cpp:
        # Run C++ engine
        # Signature: prices, signals, atr, leverage, start_balance, sl_ratio, sl_multiplier, tp_ratio, fee
        prices = df['close'].values.astype(np.float64)
        signals = df['final_signal'].values.astype(np.int32)
        atr_vec = df['atr'].values.astype(np.float64)
        
        leverage = int(config.get('leverage', 1))
        sl_ratio = float(config.get('sl_ratio', 0.03)) 
        tp_ratio = float(config.get('tp_ratio', 0.8)) # Default or from config
        
        sl_mult = float(config.get('sl_multiplier', 0.0))
        start_bal = float(getattr(cfg, 'START_BALANCE', 100.0))
        fee_rate = float(getattr(cfg, 'FEE_RATE', 0.001))
        
        res = cpp_engine.fast_backtest(prices, signals, atr_vec, leverage, start_bal, sl_ratio, sl_mult, tp_ratio, fee_rate)
        
        return res['balance'], res['wins'], res['trades'], res['mdd'], res['balance']
    else:
        # Python Slow Backtest (Legacy)
        state = TradeStateManager(config)
        test_df = df.reset_index(drop=True)
        
        # 데이터프레임 순회
        for i in range(len(test_df) - 1):
            price = test_df['close'].iloc[i]
            signal = test_df['final_signal'].iloc[i]
            state.process_tick(price, signal)

        return state.balance, state.wins, state.trades, state.max_drawdown, state.balance