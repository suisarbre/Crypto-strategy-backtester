import numpy as np
import pandas as pd
import ta
import config as cfg
import os
from sklearn.neighbors import KNeighborsClassifier
from .base import BaseStrategy

class LorentzianStrategy(BaseStrategy):
    """
    Implements the Lorentzian Distance Classification Strategy.
    Includes:
    - Rational Quadratic Kernel (for feature engineering)
    - KNN Classification (for raw signal)
    - Volatility & Trend Filters (Confirmation)
    """

    def calculate_indicators(self, df):
        df = df.copy()
        
        # 1. Basic Sources
        df['src'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        
        # 2. Parameters (Safe Get)
        rsi_len = int(self.config.get('rsi_length', 14))
        wt_ch_len = int(self.config.get('wt_channel_len', 10))
        wt_avg_len = int(self.config.get('wt_avg_len', 21))
        cci_len = int(self.config.get('cci_length', 20))
        adx_len = int(self.config.get('adx_length', 14))
        atr_period = getattr(cfg, 'ATR_PERIOD', 14)

        # 3. Calculate Indicators
        # RSI
        df['rsi'] = ta.momentum.rsi(df['src'], window=rsi_len).fillna(50)
        
        # WaveTrend (WT)
        esa = ta.trend.ema_indicator(df['src'], window=wt_ch_len)
        d = ta.trend.ema_indicator((df['src'] - esa).abs(), window=wt_ch_len)
        ci = (df['src'] - esa) / (0.015 * d)
        df['wt1'] = ta.trend.ema_indicator(ci, window=wt_avg_len).fillna(0) # WT1 is the one used in features

        # CCI
        df['cci'] = ta.trend.cci(df['high'], df['low'], df['src'], window=cci_len).fillna(0)
        
        # ADX
        df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=adx_len).fillna(0)
        
        # ATR (for Stops)
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=atr_period).fillna(0)
        
        # EMA (for Trend Filter)
        ema_period = int(self.config.get('ema_period', 200))
        df['ema'] = ta.trend.ema_indicator(df['close'], window=ema_period).fillna(df['close'])
        
        # Kernel (Lorentzian Feature)
        if self.config.get('use_kernel', False):
             self._calculate_kernel(df)
        else:
             df['kernel_rising'] = df['close'] > df['close'].shift(1)
             df['kernel_falling'] = df['close'] < df['close'].shift(1)

        return df

    def _calculate_kernel(self, df):
        # Rational Quadratic Kernel Implementation
        lookback = int(self.config.get('kernel_lookback', 8))
        weight = float(self.config.get('kernel_weight', 8.0))
        lookback_mult = getattr(cfg, 'KERNEL_LOOKBACK_MULT', 5)
        
        src = df['src'].values
        y_hat = np.copy(src)
        length = len(src)
        
        # Note: In a real optimized scenario, used pandas rolling or C++
        # Here we use the Python loop for compatibility with original code
        # But optimized slightly?
        
        for i in range(length):
            current_weight = 0.0
            cumulative_weight = 0.0
            start_j = max(0, i - lookback * lookback_mult)
            
            for j in range(start_j, i + 1):
                # RQ Kernel Formula
                w = (1 + (np.power(i - j, 2) / (2 * np.power(weight, 2)))) ** (-weight)
                current_weight += src[j] * w
                cumulative_weight += w
                
            if cumulative_weight != 0:
                y_hat[i] = current_weight / cumulative_weight
                
        df['kernel'] = y_hat
        df['kernel_rising'] = df['kernel'] > df['kernel'].shift(1)
        df['kernel_falling'] = df['kernel'] < df['kernel'].shift(1)

    def generate_signals(self, df):
        df = df.copy()
        
        # 1. Target Gen
        df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, -1)
        
        # 2. Feature selection
        feature_cols = ['rsi', 'wt1', 'cci', 'adx']
        
        # 3. Clean
        if df[feature_cols].isnull().values.any():
            valid_df = df.dropna().copy()
        else:
            valid_df = df.copy()
            
        X = valid_df[feature_cols].values
        y = valid_df['target'].values
        
        # Train on all except last
        X_train = X[:-1]
        y_train = y[:-1]
        
        # 4. KNN Prediction
        neighbors = int(self.config.get('neighbors', 8))
        
        # Try C++
        use_cpp = False
        try:
            if os.environ.get('DISABLE_CPP', '0') != '1':
                import cpp_engine
                use_cpp = True
        except ImportError:
            pass

        pred_signal = np.zeros(len(valid_df))
        
        try:
            if use_cpp:
                knn = cpp_engine.FastKNN(neighbors)
                knn.fit(X_train, y_train.astype(np.int32))
                pred_signal = knn.predict(X.astype(np.float64))
            else:
                knn = KNeighborsClassifier(n_neighbors=neighbors, metric='manhattan')
                knn.fit(X_train, y_train)
                pred_signal = knn.predict(X)
        except Exception as e:
            print(f"KNN Logic Error: {e}")
            
        df.loc[valid_df.index, 'pred_signal'] = pred_signal
        
        # 5. Apply Filters (Python Logic replacing Strategies.json)
        # Filters: EMA, ADX, Volatility
        
        # Default Masks
        long_mask = (df['pred_signal'] == 1)
        short_mask = (df['pred_signal'] == -1)
        
        # EMA Filter
        if self.config.get('use_ema_filter', False):
            # Long: Close > EMA, Short: Close < EMA
            long_mask &= (df['close'] > df['ema'])
            short_mask &= (df['close'] < df['ema'])
            
        # ADX Filter
        if self.config.get('use_adx_filter', False):
            # ADX > Threshold
            thresh = float(self.config.get('adx_threshold', 20.0))
            long_mask &= (df['adx'] > thresh)
            short_mask &= (df['adx'] > thresh)
            
        # Volatility Filter (Kernel/Price Direction Confirmation)
        # Original logic: 'kernel_rising' for Long, 'kernel_falling' for Short
        if 'kernel_rising' in df.columns:
             long_mask &= (df['kernel_rising'] == True)
             short_mask &= (df['kernel_falling'] == True)
             
        # Combine
        df['final_signal'] = 0
        df.loc[long_mask, 'final_signal'] = 1
        df.loc[short_mask, 'final_signal'] = -1
        
        return df

    def get_parameter_ranges(self):
        # Research-backed ranges from jdehorty's KNN Lorentzian Classification
        return {
            'rsi_length':     [9, 11, 14, 17, 21],
            'wt_channel_len': [8, 9, 10, 11, 14],
            'wt_avg_len':     [9, 11, 13, 15],
            'cci_length':     [14, 17, 20, 23, 26],
            'adx_length':     [14, 17, 20, 23, 26],
            'rsi2_length':    [5, 7, 9, 11, 14],
            'neighbors':      [6, 8, 10, 12, 16],
            'adx_threshold':  [15, 20, 25, 30],
            'use_ema_filter':  [0, 1],
            'use_adx_filter':  [0, 1],
        }
        
    def process_signal(self, state, price, signal, atr=0.0, extras=None):
        # Use Standard Execution Logic (Trailing Stop etc)
        # For now, duplicate standard logic to be safe/standalone
        logs = []
        if extras is None: extras = {}
        
        # Configs
        use_ts = self.config.get('use_trailing_stop', True)
        ts_mult = float(self.config.get('sl_multiplier', 3.0))
        
        # [Refactor] Trailing Stop is now handled by Core (TradeStateManager)
        # We only handle Entry Logic here.
                    
        # 2. Entry Logic
        if signal == 1:
            if state.position == -1:
                 pnl = self.get_pnl(state, price)
                 logs.append(state.close_position(price, "Switch", pnl))
            if state.position == 0:
                state.open_position(1, price, atr)
                logs.append(f"🔵 [Lorentzian] Buy @ {price}")
                
        elif signal == -1:
             if state.position == 1:
                 pnl = self.get_pnl(state, price)
                 logs.append(state.close_position(price, "Switch", pnl))
             if state.position == 0:
                state.open_position(-1, price, atr)
                logs.append(f"🔴 [Lorentzian] Sell @ {price}")
                
        return logs
