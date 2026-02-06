import config  # 설정 파일 임포트
import ccxt
import pandas as pd
import ta
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
import time
import schedule
from datetime import datetime
import warnings
import socket
import itertools
import threading
import requests.packages.urllib3.util.connection as urllib3_cn


# IPv4 강제 설정
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family


warnings.filterwarnings('ignore')


# ==========================================
# 1. 설정 불러오기
# ==========================================
API_KEY = config.API_KEY
SECRET_KEY = config.SECRET_KEY
SYMBOL = config.SYMBOL
TIMEFRAME = config.TIMEFRAME
MAX_FETCH_LIMIT = config.MAX_FETCH_LIMIT


CURRENT_CONFIG = config.CURRENT_CONFIG.copy()


OPTIMIZE_INTERVAL_MINUTES = config.OPTIMIZE_INTERVAL_MINUTES
is_optimizing = False


exchange = ccxt.binanceus({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})


# ==========================================
# 2. 지표 계산
# ==========================================
def get_rational_quadratic_kernel(src, lookback, relative_weight):
    y_hat = src.copy()
    src_np = src.values
    length = len(src)
    calc_start = max(0, length - 2000)
   
    for i in range(calc_start, length):
        current_weight = 0.0
        cumulative_weight = 0.0
        for j in range(max(0, i - lookback * 5), i + 1):
            w = (1 + (np.power(i - j, 2) / (2 * np.power(relative_weight, 2)))) ** (-relative_weight)
            current_weight += src_np[j] * w
            cumulative_weight += w
        if cumulative_weight != 0:
            y_hat.iloc[i] = current_weight / cumulative_weight
    return y_hat


def add_indicators(df, config):
    df = df.copy()
    df['src'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4


    df['rsi'] = ta.momentum.rsi(df['src'], window=int(config['rsi_length'])).fillna(50)
   
    esa = ta.trend.ema_indicator(df['src'], window=int(config['wt_channel_len']))
    d = ta.trend.ema_indicator((df['src'] - esa).abs(), window=int(config['wt_channel_len']))
    ci = (df['src'] - esa) / (0.015 * d)
    df['wt1'] = ta.trend.ema_indicator(ci, window=int(config['wt_avg_len'])).fillna(0)


    df['cci'] = ta.trend.cci(df['high'], df['low'], df['src'], window=int(config['cci_length'])).fillna(0)
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=int(config['adx_length'])).fillna(0)
    df['ema_200'] = ta.trend.ema_indicator(df['src'], window=200).fillna(0)


    if config['use_kernel']:
        df['kernel'] = get_rational_quadratic_kernel(df['src'], config['kernel_lookback'], config['kernel_weight'])
        df['kernel_rising'] = df['kernel'] > df['kernel'].shift(1)
        df['kernel_falling'] = df['kernel'] < df['kernel'].shift(1)
    else:
        df['kernel_rising'] = True
        df['kernel_falling'] = True
       
    df.dropna(inplace=True)
    return df


def fetch_raw_data(symbol, timeframe, limit):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"데이터 에러: {e}")
        return None


# ==========================================
# 3. 신호 생성
# ==========================================
def generate_signals(df, config):
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, -1)
   
    feature_cols = ['rsi', 'wt1', 'cci', 'adx']
    X = df[feature_cols].values
    y = df['target'].values
   
    X_train = X[:-1]
    y_train = y[:-1]
   
    knn = KNeighborsClassifier(n_neighbors=int(config['neighbors']), metric='manhattan')
    knn.fit(X_train, y_train)
   
    df['pred_signal'] = knn.predict(X)
   
    long_cond = (
        (df['pred_signal'] == 1) &
        (df['adx'] > config['adx_threshold']) &
        (df['src'] > df['ema_200']) &
        (df['kernel_rising'] == True)
    )
   
    short_cond = (
        (df['pred_signal'] == -1) &
        (df['adx'] > config['adx_threshold']) &
        (df['src'] < df['ema_200']) &
        (df['kernel_falling'] == True)
    )
   
    df['final_signal'] = np.where(long_cond, 1,
                                  np.where(short_cond, -1, 0))
    return df


# ==========================================
# 4. 백테스팅 (수정됨: 레버리지 반영 손절)
# ==========================================
def run_deep_backtest(df, config):
    balance = 100.0
    position = 0
    entry_price = 0
    wins = 0
    total_trades = 0
    sl = config['sl_ratio']
   
    current_leverage = config['leverage']
   
    peak_balance = 100.0
    max_drawdown = 0.0
   
    test_df = df.reset_index(drop=True)
   
    for i in range(len(test_df) - 1):
        price = test_df['close'].iloc[i]
        signal = test_df['final_signal'].iloc[i]
       
        # 진입
        if position == 0:
            if signal == 1:
                position = 1; entry_price = price; total_trades += 1
            elif signal == -1:
                position = -1; entry_price = price; total_trades += 1
               
        # Long 관리
        elif position == 1:
            raw_pnl = (price - entry_price) / entry_price
            lev_pnl = raw_pnl * current_leverage
           
            # [수정] 손절 조건을 lev_pnl(내 원금 대비 손익)로 변경
            if lev_pnl <= -sl or signal == -1:
                balance *= (1 + lev_pnl - 0.001)
                if lev_pnl > 0: wins += 1
                if signal == -1: position = -1; entry_price = price; total_trades += 1
                else: position = 0


        # Short 관리
        elif position == -1:
            raw_pnl = (entry_price - price) / entry_price
            lev_pnl = raw_pnl * current_leverage
           
            # [수정] 손절 조건을 lev_pnl(내 원금 대비 손익)로 변경
            if lev_pnl <= -sl or signal == 1:
                balance *= (1 + lev_pnl - 0.001)
                if lev_pnl > 0: wins += 1
                if signal == 1: position = 1; entry_price = price; total_trades += 1
                else: position = 0
               
        # MDD 업데이트
        if balance > peak_balance: peak_balance = balance
        drawdown = (peak_balance - balance) / peak_balance
        if drawdown > max_drawdown: max_drawdown = drawdown


    return balance, wins, total_trades, max_drawdown, balance


# ==========================================
# 5. 최적화 로직
# ==========================================
def execute_optimization_logic():
    print(f"\n[{datetime.now().strftime('%H:%M')}] ⚙️ 지표 및 레버리지(1~10x) 정밀 최적화 시작...")
   
    df_raw_origin = fetch_raw_data(SYMBOL, TIMEFRAME, MAX_FETCH_LIMIT)
    if df_raw_origin is None: return None, 0, 0, 0, 0
   
    best_score = -999
    best_params = CURRENT_CONFIG.copy()
    best_wins = 0; best_trades = 0; best_mdd = 0; best_balance = 100.0
   
    bars_list = [2000, 3000]
   
    def get_range(val, step=2): return [val - step, val, val + step]


    rsi_range = get_range(CURRENT_CONFIG['rsi_length'])
    wt_ch_range = get_range(CURRENT_CONFIG['wt_channel_len'])
    wt_avg_range = get_range(CURRENT_CONFIG['wt_avg_len'])
    cci_range = get_range(CURRENT_CONFIG['cci_length'], 3)
    adx_len_range = get_range(CURRENT_CONFIG['adx_length'])
    adx_th_range = [15, 20, 25]
    k_range = get_range(CURRENT_CONFIG['neighbors'])
   
    leverage_range = range(1, 11)
   
    total_iter = (len(bars_list) * len(rsi_range) * len(wt_ch_range) * len(wt_avg_range) * len(cci_range) * len(adx_len_range))
    count = 0
   
    for bars in bars_list:
        df_slice_raw = df_raw_origin.tail(bars).copy().reset_index(drop=True)
        ind_params = itertools.product(rsi_range, wt_ch_range, wt_avg_range, cci_range, adx_len_range)
       
        for r_len, wt_ch, wt_av, c_len, a_len in ind_params:
            count += 1
           
            temp_config = CURRENT_CONFIG.copy()
            temp_config.update({
                'max_bars_back': bars,
                'rsi_length': r_len,
                'wt_channel_len': wt_ch,
                'wt_avg_len': wt_av,
                'cci_length': c_len,
                'adx_length': a_len
            })
           
            df_with_ind = add_indicators(df_slice_raw.copy(), temp_config)
            sub_params = itertools.product(adx_th_range, k_range)
           
            for adx_th, k in sub_params:
                iter_cfg = temp_config.copy()
                iter_cfg.update({'adx_threshold': adx_th, 'neighbors': k})
               
                sig_df = generate_signals(df_with_ind.copy(), iter_cfg)
               
                for lev in leverage_range:
                    iter_cfg['leverage'] = lev
                   
                    final_bal, wins, trades, mdd, _ = run_deep_backtest(sig_df, iter_cfg)
                   
                    if trades < 7:
                        score = -999
                    else:
                        profit_ratio = (final_bal - 100) / 100
                        win_rate = wins / trades
                        score = (profit_ratio * win_rate) / (mdd + 0.05)
                        if mdd > 0.3: score = -999


                    if score > best_score:
                        best_score = score
                        best_params = iter_cfg.copy()
                        best_wins = wins
                        best_trades = trades
                        best_mdd = mdd
                        best_balance = final_bal
           
            if count % 10 == 0:
                prog = (count / total_iter) * 100
                curr_profit = (best_balance - 100)
                best_lev = best_params.get('leverage', 1)
                print(f"진행:{prog:.1f}% | Best: {best_lev}x, 수익:{curr_profit:+.1f}%, MDD:{best_mdd*100:.1f}%", end='\r')


    return best_params, best_wins, best_trades, best_mdd, best_balance


def optimize_parameters_worker():
    global CURRENT_CONFIG, is_optimizing
    if is_optimizing: return


    is_optimizing = True
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🔄 백그라운드 최적화 시작...")
    try:
        new_params, wins, trades, mdd, final_bal = execute_optimization_logic()
       
        if new_params:
            CURRENT_CONFIG = new_params
            win_rate = (wins/trades*100) if trades > 0 else 0
            total_profit = (final_bal - 100)
            best_lev = CURRENT_CONFIG['leverage']
           
            print(f"\n✅ [System] 최적화 완료! (적용 레버리지: {best_lev}x)")
            print(f"   📊 결과: 수익 {total_profit:+.2f}% / 승률 {win_rate:.1f}% / MDD {mdd*100:.1f}%")
           
    except Exception as e:
        print(f"\n[Error] 최적화 오류: {e}")
    finally:
        is_optimizing = False


def start_optimization_thread():
    t = threading.Thread(target=optimize_parameters_worker, daemon=True)
    t.start()


# ==========================================
# 6. 메인 매매 로직
# ==========================================
paper_balance_usdt = 100.0
paper_coin_amount = 0.0
paper_avg_entry = 0.0
paper_position = 0
paper_partial_done = False
paper_wins = 0; paper_trades = 0


def update_stats(lev_pnl):
    global paper_wins, paper_trades
    paper_trades += 1
    if lev_pnl > 0: paper_wins += 1


def monitor_position():
    if paper_position == 0:
        print(f"\r[{datetime.now().strftime('%H:%M:%S')}] 대기중... 포지션 없음", end='')
        return


    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        current_price = ticker['last']
        current_lev = CURRENT_CONFIG.get('leverage', 5)
       
        if paper_position == 1:
            raw_pnl = (current_price - paper_avg_entry) / paper_avg_entry
        else:
            raw_pnl = (paper_avg_entry - current_price) / paper_avg_entry
           
        lev_pnl = raw_pnl * current_lev
        unrealized_profit = paper_balance_usdt * lev_pnl
        est_balance = paper_balance_usdt + unrealized_profit
       
        pos_str = f"🟢 LONG({current_lev}x)" if paper_position == 1 else f"🔴 SHORT({current_lev}x)"
       
        print(f"\r[{datetime.now().strftime('%H:%M:%S')}] {pos_str} | 현재가: {current_price} | PNL: {lev_pnl*100:+.2f}% (${unrealized_profit:+.2f}) | 잔고: ${est_balance:.2f}", end='')
       
    except Exception as e:
        pass


def trade_job():
    global paper_balance_usdt, paper_coin_amount, paper_avg_entry, paper_position, paper_partial_done, CURRENT_CONFIG
   
    print()
    print(f"--- [Candle Close] {datetime.now().strftime('%H:%M:%S')} ---")


    df = fetch_raw_data(SYMBOL, TIMEFRAME, MAX_FETCH_LIMIT)
    if df is None: return
   
    if len(df) > CURRENT_CONFIG['max_bars_back']:
        df = df.tail(CURRENT_CONFIG['max_bars_back']).copy().reset_index(drop=True)
   
    df = add_indicators(df, CURRENT_CONFIG)
    df = generate_signals(df, CURRENT_CONFIG)
   
    sig = df['final_signal'].iloc[-1]
    price = df['close'].iloc[-1]
    current_lev = CURRENT_CONFIG.get('leverage', 5)
   
    est_value = paper_balance_usdt
    pnl_str = ""
   
    if paper_position != 0:
        if paper_position == 1:
            raw_pnl = (price - paper_avg_entry) / paper_avg_entry
        else:
            raw_pnl = (paper_avg_entry - price) / paper_avg_entry
           
        lev_pnl = raw_pnl * current_lev
        unrealized_profit = paper_balance_usdt * lev_pnl
        est_value = paper_balance_usdt + unrealized_profit
        pnl_str = f"| PnL: {raw_pnl*100:+.2f}% (ROI: {lev_pnl*100:+.2f}%)"


    sig_str = "Long 진입" if sig==1 else ("Short 진입" if sig==-1 else "관망")
    pos_str = "LONG" if paper_position==1 else ("SHORT" if paper_position==-1 else "NONE")
    wr = (paper_wins/paper_trades*100) if paper_trades>0 else 0
   
    print(f"봉마감 P:{price:.1f} | 신호:{sig_str} | 보유:{pos_str} {pnl_str} | 확정잔고:${paper_balance_usdt:.2f} (승률:{wr:.1f}%) | Lev:{current_lev}x")


    if sig == 1:
        if paper_position == -1: close_short(price, "롱 스위칭")
        if paper_position == 0: open_long(price)
           
    elif sig == -1:
        if paper_position == 1: close_long(price, "숏 스위칭")
        if paper_position == 0: open_short(price)


    if paper_position != 0:
        manage_position(price, sig)


def open_long(price):
    global paper_position, paper_coin_amount, paper_avg_entry, paper_balance_usdt, paper_partial_done
   
    lev = CURRENT_CONFIG.get('leverage', 5)
    collateral = paper_balance_usdt
    position_size = collateral * lev
    paper_coin_amount = position_size / price
    paper_avg_entry = price
    paper_position = 1
    paper_partial_done = False
    print(f"  🚀 [LONG {lev}x] 진입 @ {price}")


def open_short(price):
    global paper_position, paper_coin_amount, paper_avg_entry, paper_balance_usdt, paper_partial_done
   
    lev = CURRENT_CONFIG.get('leverage', 5)
    collateral = paper_balance_usdt
    position_size = collateral * lev
    paper_coin_amount = position_size / price
    paper_avg_entry = price
    paper_position = -1
    paper_partial_done = False
    print(f"  ⬇️ [SHORT {lev}x] 진입 @ {price}")


def close_long(price, msg):
    global paper_position, paper_coin_amount, paper_balance_usdt
    lev = CURRENT_CONFIG.get('leverage', 5)
   
    raw_pnl = (price - paper_avg_entry) / paper_avg_entry
    lev_pnl = raw_pnl * lev
    paper_balance_usdt = paper_balance_usdt * (1 + lev_pnl - 0.001)
    paper_coin_amount = 0; paper_position = 0
    update_stats(lev_pnl)
    print(f"  Long 청산 [{msg}]: {price} (ROI: {lev_pnl*100:.2f}%)")


def close_short(price, msg):
    global paper_position, paper_coin_amount, paper_balance_usdt
    lev = CURRENT_CONFIG.get('leverage', 5)
   
    raw_pnl = (paper_avg_entry - price) / paper_avg_entry
    lev_pnl = raw_pnl * lev
    paper_balance_usdt = paper_balance_usdt * (1 + lev_pnl - 0.001)
    paper_coin_amount = 0; paper_position = 0
    update_stats(lev_pnl)
    print(f"  Short 청산 [{msg}]: {price} (ROI: {lev_pnl*100:.2f}%)")


def manage_position(price, sig):
    global paper_partial_done, paper_balance_usdt, paper_coin_amount
    sl = CURRENT_CONFIG['sl_ratio']
    lev = CURRENT_CONFIG.get('leverage', 5)
   
    if paper_position == 1:
        raw_pnl = (price - paper_avg_entry) / paper_avg_entry
        lev_pnl = raw_pnl * lev  # [수정] ROI 계산
       
        # [수정] lev_pnl 기준으로 손절 체크
        if lev_pnl <= -sl:
            close_long(price, "손절")
        elif sig == 0 and not paper_partial_done:
            print(f"  🌊 [Long] Default Exit (절반청산 시늉) ROI:{lev_pnl*100:.2f}%")
            paper_partial_done = True
           
    elif paper_position == -1:
        raw_pnl = (paper_avg_entry - price) / paper_avg_entry
        lev_pnl = raw_pnl * lev # [수정] ROI 계산
       
        # [수정] lev_pnl 기준으로 손절 체크
        if lev_pnl <= -sl:
            close_short(price, "손절")
        elif sig == 0 and not paper_partial_done:
            print(f"  🌊 [Short] Default Exit (절반청산 시늉) ROI:{lev_pnl*100:.2f}%")
            paper_partial_done = True


def manage_position_scheduled():
    """Wrapper to run manage_position every 10 seconds with current market data"""
    if paper_position == 0:
        return
   
    try:
        df = fetch_raw_data(SYMBOL, TIMEFRAME, MAX_FETCH_LIMIT)
        if df is None: return
       
        price = df['close'].iloc[-1]
        sig = 0  # Default to neutral signal for continuous position management
       
        manage_position(price, sig)
    except Exception as e:
        pass


def run_scheduler():
    global CURRENT_CONFIG
    print(f"=== Lorentzian Bot (Risk on Equity Version) ===")
    print("1. 초기 최적화 시작 (레버리지 포함)...")
   
    i_params, w, t, m, b = execute_optimization_logic()
   
    if i_params:
        CURRENT_CONFIG = i_params
        best_lev = CURRENT_CONFIG['leverage']
        print(f"\n✅ 초기화 완료. 레버리지: {best_lev}x | MDD:{m*100:.1f}% | 승률:{(w/t*100):.1f}%")
   
    schedule.every(OPTIMIZE_INTERVAL_MINUTES).minutes.do(start_optimization_thread)
    schedule.every(5).minutes.do(trade_job)
    schedule.every(10).seconds.do(monitor_position)
    schedule.every(10).seconds.do(manage_position_scheduled)
   
    trade_job()
   
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_scheduler()


