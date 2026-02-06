#include "backtester.h"
#include <iostream>

BacktestResult fast_backtest_internal(
    const std::vector<double>& prices, 
    const std::vector<int>& signals, 
    const std::vector<double>& atr,
    int leverage, 
    double start_balance, 
    double sl_ratio, 
    double sl_multiplier,
    double tp_ratio, 
    double fee
) {
    size_t n = prices.size();
    if (n != signals.size()) return {start_balance, 0, 0, 0.0};

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
    double trailing_stop_price = 0.0; // [NEW]
    
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
                 // Dynamic SL: (ATR * Multiplier) / EntryPrice
                 current_sl_ratio = (entry_atr * sl_multiplier) / avg_entry;
            }
            
            // Check SL
            if (lev_pnl <= -current_sl_ratio) {
                // SL Hit -> Close Remaining
                double final_pnl = lev_pnl;
                
                if (partial_done) {
                    final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                }
                
                double leverage_fee = fee * leverage;
                balance *= (1.0 + final_pnl - leverage_fee);
                
                if (balance <= 0) {
                    balance = 0;
                    position = 0;
                    break;
                }
                
                // Reset State
                position = 0;
                partial_done = false;
                partial_pnl = 0.0;
            }
            // Check TP
            else if (tp_ratio > 0 && lev_pnl >= tp_ratio) {
                 double final_pnl = lev_pnl;
                 if (partial_done) final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                 
                  double leverage_fee = fee * leverage;
                  balance *= (1.0 + final_pnl - leverage_fee);
                  
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
        }
        
        // --- 2. Signal Processing ---
        
        // Case A: Signal 0 (Neutral) -> Check Partial Exit
        if (signal == 0) {
            if (position != 0 && !partial_done) {
                // Execute Partial Exit (50%)
                double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
                double lev_pnl = raw_pnl * leverage;
                
                partial_done = true;
                partial_pnl = lev_pnl;
                
                // Init TS Price (Breakeven or secure)
                double current_entry_atr = (i < atr.size()) ? atr[i] : 0.0; 
                // But usually we trail from Price.
                // Let's safe-guard: Long -> max(entry, price - mul*ATR)
                // Simply init to 0.0 (inactive) then let loop update it? No, loop updates on next tick.
                // We should init it HERE to be safe for next tick logic.
                if (position == 1) {
                    trailing_stop_price = price - (current_entry_atr * sl_multiplier);
                    if (trailing_stop_price < avg_entry) trailing_stop_price = avg_entry; // Secure Breakeven
                } else {
                    trailing_stop_price = price + (current_entry_atr * sl_multiplier);
                    if (trailing_stop_price > avg_entry) trailing_stop_price = avg_entry;
                }
            }
        }
        
        // Case B: Signal Opposite or New Entry
        else if (signal != 0) {
            // If we have a position and signal is different (Switch or Close/Re-entry)
            if (position != 0 && signal != position) {
                // Close current position
                double raw_pnl = (position == 1) ? (price - avg_entry) / avg_entry : (avg_entry - price) / avg_entry;
                double lev_pnl = raw_pnl * leverage;
                
                double final_pnl = lev_pnl;
                if (partial_done) {
                    final_pnl = (partial_pnl * 0.5) + (lev_pnl * 0.5);
                }
                
                double leverage_fee = fee * leverage;
                balance *= (1.0 + final_pnl - leverage_fee);
                
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
            
            // Open new position (if we just closed, this won't be hit due to 'continue'. 
            // If we were flat, this is hit.)
            if (position == 0) {
                position = signal;
                avg_entry = price;
                entry_atr = (i < atr.size()) ? atr[i] : 0.0; // Capture ATR at entry
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
    
    return {balance, wins, trades, max_mdd};
}


py::dict fast_backtest_wrapper(
    py::array_t<double> prices_arg, 
    py::array_t<int> signals_arg, 
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
    auto atr_buf = atr_arg.request();
    
    double* ptr_prices = static_cast<double*>(prices_buf.ptr);
    int* ptr_signals = static_cast<int*>(signals_buf.ptr);
    double* ptr_atr = static_cast<double*>(atr_buf.ptr);
    
    size_t n = prices_buf.shape[0];
    std::vector<double> prices(ptr_prices, ptr_prices + n);
    std::vector<int> signals(ptr_signals, ptr_signals + n);
    std::vector<double> atr(ptr_atr, ptr_atr + n);
    
    auto res = fast_backtest_internal(prices, signals, atr, leverage, start_balance, sl_ratio, sl_multiplier, tp_ratio, fee);
    
    py::dict d;
    d["balance"] = res.balance;
    d["wins"] = res.wins;
    d["trades"] = res.trades;
    d["mdd"] = res.mdd;
    return d;
}
