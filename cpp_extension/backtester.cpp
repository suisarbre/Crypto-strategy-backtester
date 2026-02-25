#include "backtester.h"
#include <iostream>
#include <cmath>
#include <algorithm>

BacktestResult fast_backtest_internal(
    const std::vector<double>& prices, 
    const std::vector<int>& signals, 
    const std::vector<int>& exit_signals, // Bitmask: 1=LongExit, 2=ShortExit
    const std::vector<double>& atr,
    int leverage, 
    double start_balance, 
    double sl_ratio, 
    double sl_multiplier,
    double tp_ratio, 
    double fee
) {
    size_t n = prices.size();
    if (n != signals.size()) return {start_balance, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};

    double balance = start_balance;
    int position = 0; // 0, 1, -1
    double avg_entry = 0.0;
    double entry_atr = 0.0; // Store ATR at entry
    
    int wins = 0;
    int trades = 0;
    double peak_balance = start_balance;
    double max_mdd = 0.0;
    
    // Partial Exit State
    bool partial_done = false;
    double partial_pnl = 0.0;
    double trailing_stop_price = 0.0;
    
    // [Benchmarking] Risk-adjusted metrics tracking (per Architecture Report)
    double sum_sq_neg_returns = 0.0;  // Sum of squared negative trade returns (for Sortino downside deviation)
    int neg_return_count = 0;
    double gross_profit = 0.0;        // Sum of positive trade PnLs (for Profit Factor)
    double gross_loss = 0.0;          // Sum of |negative trade PnLs| (for Profit Factor)
    
    // Helper: Record a completed trade's net return for risk metrics
    auto record_trade_metrics = [&](double net_return) {
        if (net_return < 0) {
            sum_sq_neg_returns += net_return * net_return;
            neg_return_count++;
            gross_loss += std::abs(net_return);
        } else {
            gross_profit += net_return;
        }
    };
    
    for (size_t i = 0; i < n; ++i) {
        double price = prices[i];
        int signal = signals[i];
        
        // --- 1. Position Management & Risk Control ---
        if (position != 0) {
            double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
            double lev_pnl = raw_pnl * leverage;
            
            // Determine Current SL Ratio
            double current_sl_ratio = sl_ratio;
            if (sl_multiplier > 0.0 && entry_atr > 0.0 && avg_entry > 0.0) {
                 current_sl_ratio = (entry_atr * sl_multiplier) / avg_entry;
            }
            
            // Check SL
            if (lev_pnl <= -current_sl_ratio) {
                double final_pnl = lev_pnl;
                
                if (partial_done) {
                    final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                }
                
                double leverage_fee = fee * leverage;
                double net_return = final_pnl - leverage_fee;
                balance *= (1.0 + net_return);
                record_trade_metrics(net_return);
                
                if (balance <= 0) {
                    balance = 0;
                    position = 0;
                    break;
                }
                
                position = 0;
                partial_done = false;
                partial_pnl = 0.0;
                trailing_stop_price = 0.0;
            }
            // Check TP
            else if (tp_ratio > 0 && lev_pnl >= tp_ratio) {
                 double final_pnl = lev_pnl;
                 if (partial_done) final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                 
                 double leverage_fee = fee * leverage;
                 double net_return = final_pnl - leverage_fee;
                 balance *= (1.0 + net_return);
                 record_trade_metrics(net_return);
                  
                 if (balance <= 0) {
                     balance = 0;
                     position = 0;
                     break;
                 }
                 if (final_pnl > 0) wins++;
                 
                 position = 0;
                 partial_done = false;
                 partial_pnl = 0.0;
                 trailing_stop_price = 0.0;
            }
            // Check Trailing Stop (active after partial exit)
            else if (partial_done && trailing_stop_price > 0.0) {
                 bool ts_hit = false;
                 if (position == 1 && price <= trailing_stop_price) ts_hit = true;
                 if (position == -1 && price >= trailing_stop_price) ts_hit = true;
                 
                 // Update trailing stop (ratchet in profit direction)
                 if (!ts_hit) {
                     double current_atr = (i < atr.size()) ? atr[i] : 0.0;
                     if (position == 1) {
                         double new_ts = price - (current_atr * sl_multiplier);
                         if (new_ts > trailing_stop_price) trailing_stop_price = new_ts;
                     } else {
                         double new_ts = price + (current_atr * sl_multiplier);
                         if (new_ts < trailing_stop_price) trailing_stop_price = new_ts;
                     }
                 }
                 
                 if (ts_hit) {
                     double final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                     double leverage_fee = fee * leverage;
                     double net_return = final_pnl - leverage_fee;
                     balance *= (1.0 + net_return);
                     record_trade_metrics(net_return);
                     
                     if (balance <= 0) {
                         balance = 0;
                         position = 0;
                         break;
                     }
                     if (final_pnl > 0) wins++;
                     
                     position = 0;
                     partial_done = false;
                     partial_pnl = 0.0;
                     trailing_stop_price = 0.0;
                 }
            }
        }
        
        // --- 2. Signal Processing ---
        
        // Check Explicit Exit Signals
        if (i < exit_signals.size()) {
             int exit_mask = exit_signals[i];
             bool do_exit = false;
             
             if (position == 1 && (exit_mask & 1)) do_exit = true;
             if (position == -1 && (exit_mask & 2)) do_exit = true;
             
             if (do_exit) {
                  double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
                  double lev_pnl = raw_pnl * leverage;
                  double leverage_fee = fee * leverage;
                  
                  double final_pnl = lev_pnl;
                  if (partial_done) final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                  
                  double net_return = final_pnl - leverage_fee;
                  balance *= (1.0 + net_return);
                  record_trade_metrics(net_return);
                  if (final_pnl > 0) wins++;
                  
                  position = 0;
                  partial_done = false;
                  partial_pnl = 0.0;
                  avg_entry = 0.0;
             }
        }
        
        // Case A: Signal 0 (Neutral) -> Check Partial Exit
        if (signal == 0) {
            if (position != 0 && !partial_done) {
                double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
                double lev_pnl = raw_pnl * leverage;
                
                partial_done = true;
                partial_pnl = lev_pnl;
                
                double current_entry_atr = (i < atr.size()) ? atr[i] : 0.0; 
                if (position == 1) {
                    trailing_stop_price = price - (current_entry_atr * sl_multiplier);
                    if (trailing_stop_price < avg_entry) trailing_stop_price = avg_entry;
                } else {
                    trailing_stop_price = price + (current_entry_atr * sl_multiplier);
                    if (trailing_stop_price > avg_entry) trailing_stop_price = avg_entry;
                }
            }
        }
        
        // Case B: Signal Opposite or New Entry
        else if (signal != 0) {
            if (position != 0 && signal != position) {
                double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
                double lev_pnl = raw_pnl * leverage;
                
                double final_pnl = lev_pnl;
                if (partial_done) {
                    final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                }
                
                double leverage_fee = fee * leverage;
                double net_return = final_pnl - leverage_fee;
                balance *= (1.0 + net_return);
                record_trade_metrics(net_return);
                
                if (balance <= 0) {
                    balance = 0;
                    position = 0;
                    break;
                }
                if (final_pnl > 0) wins++;
                
                position = 0;
                partial_done = false;
                partial_pnl = 0.0;
            }
            
            if (position == 0) {
                position = signal;
                avg_entry = price;
                entry_atr = (i < atr.size()) ? atr[i] : 0.0;
                partial_done = false;
                partial_pnl = 0.0;
                trades++;
            }
        }
        
        // Update Stats
        if (balance > peak_balance) peak_balance = balance;
        if (peak_balance > 0) {
            double dd = (peak_balance - balance) / peak_balance;
            if (dd > max_mdd) max_mdd = dd;
        }
    }
    
    // [Benchmarking] Force-close open position at end for accurate metrics
    if (position != 0 && n > 0) {
        double price = prices[n - 1];
        double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
        double lev_pnl = raw_pnl * leverage;
        double final_pnl = lev_pnl;
        if (partial_done) final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
        double leverage_fee = fee * leverage;
        double net_return = final_pnl - leverage_fee;
        balance *= (1.0 + net_return);
        record_trade_metrics(net_return);
        if (final_pnl > 0) wins++;
    }
    
    // [Benchmarking] Compute risk-adjusted metrics (per Architecture Report)
    // Total Return: percentage gain/loss from starting balance
    double total_return = (start_balance > 0) ? (balance - start_balance) / start_balance : 0.0;
    
    // Sortino Ratio: Return / Downside Deviation
    // Downside deviation = sqrt(mean of squared negative returns)
    double downside_dev = (neg_return_count > 0) 
        ? std::sqrt(sum_sq_neg_returns / neg_return_count) 
        : 0.001;
    double sortino = (downside_dev > 0.0001) ? total_return / downside_dev : 0.0;
    
    // Calmar Ratio: Return / Max Drawdown
    double calmar = (max_mdd > 0.001) 
        ? total_return / max_mdd 
        : (total_return > 0 ? total_return * 1000.0 : 0.0);
    
    // Profit Factor: Gross Profit / Gross Loss
    double profit_factor = (gross_loss > 0.0001) 
        ? gross_profit / gross_loss 
        : (gross_profit > 0 ? 999.0 : 0.0);
    
    return {balance, wins, trades, max_mdd, 0.0, total_return, sortino, calmar, profit_factor};
}


py::dict fast_backtest_wrapper(
    py::array_t<double> prices_arg, 
    py::array_t<int> signals_arg, 
    py::array_t<int> exit_signals_arg,
    py::array_t<double> atr_arg,
    int leverage, 
    double start_balance, 
    double sl_ratio, 
    double sl_multiplier,
    double tp_ratio, 
    double fee
) {
    auto prices_buf = prices_arg.request();
    auto signals_buf = signals_arg.request();
    auto exit_buf = exit_signals_arg.request();
    auto atr_buf = atr_arg.request();
    
    double* ptr_prices = static_cast<double*>(prices_buf.ptr);
    int* ptr_signals = static_cast<int*>(signals_buf.ptr);
    int* ptr_exits = static_cast<int*>(exit_buf.ptr);
    double* ptr_atr = static_cast<double*>(atr_buf.ptr);
    
    size_t n = prices_buf.shape[0];
    std::vector<double> prices(ptr_prices, ptr_prices + n);
    std::vector<int> signals(ptr_signals, ptr_signals + n);
    std::vector<int> exit_signals(ptr_exits, ptr_exits + n);
    std::vector<double> atr(ptr_atr, ptr_atr + n);
    
    auto res = fast_backtest_internal(prices, signals, exit_signals, atr, leverage, start_balance, sl_ratio, sl_multiplier, tp_ratio, fee);
    
    py::dict d;
    d["balance"] = res.balance;
    d["wins"] = res.wins;
    d["trades"] = res.trades;
    d["mdd"] = res.mdd;
    d["total_return"] = res.total_return;
    d["sortino"] = res.sortino;
    d["calmar"] = res.calmar;
    d["profit_factor"] = res.profit_factor;
    return d;
}
