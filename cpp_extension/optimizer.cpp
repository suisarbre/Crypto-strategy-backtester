#include "optimizer.h"
#include "indicators.h"
#include "knn.h"
#include "backtester.h"
#include <iostream>
#include <numeric>

// Range helper (modified to double)
std::vector<double> get_range_from_list(py::list l) {
    std::vector<double> res;
    for (auto item : l) res.push_back(item.cast<double>());
    return res;
}

std::vector<OptimizationResult> optimize_grid_search_internal(
    const std::vector<double>& open, 
    const std::vector<double>& high, 
    const std::vector<double>& low, 
    const std::vector<double>& close,
    const std::map<std::string, std::vector<double>>& ranges,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    double sl_ratio, double tp_ratio, double fee,
    int min_trades, int max_trades, double max_mdd, int ema_period,
    int atr_period, double start_balance
) {
    // 1. Data Preparation
    size_t n = close.size();
    
    // Calculate src (OHLC/4) - constant
    std::vector<double> src(n);
    for(size_t i=0; i<n; ++i) src[i] = (open[i] + high[i] + low[i] + close[i]) / 4.0;
    
    // Top K container
    int top_k = 20; // Return top 20 candidates
    std::vector<OptimizationResult> top_results;
    double min_top_score = -999.0; // Current minimum score in the top list

    // Indicators Containers
    std::vector<double> rsi_vec;
    std::vector<double> wt1_vec;
    std::vector<double> cci_vec;
    std::vector<double> adx_vec;
    std::vector<double> ema200_vec = indicators::ema(src, ema_period);
    
    // Calculate ATR (Parameterized period)
    std::vector<double> atr_vec = indicators::atr(high, low, close, atr_period);
    
    // Kernel Calculation (Standardized multiplier)
    std::vector<bool> kernel_rising(n, true); 
    std::vector<bool> kernel_falling(n, true);
    
    auto kernel = indicators::rq_kernel(src, kernel_weight, kernel_lookback, kernel_lookback_mult); 
    
    // [Trend Filter] EMA 200 (Moved to Loop)
     
    for(size_t i=1; i<n; ++i) {
        kernel_rising[i] = kernel[i] > kernel[i-1];
        kernel_falling[i] = kernel[i] < kernel[i-1];
    }
    
    // Target for KNN
    std::vector<int> target(n, 0);
    for(size_t i=0; i<n-1; ++i) {
        if(close[i+1] > close[i]) target[i] = 1;
        else target[i] = -1;
    }
    
    // Ranges extraction (Use helper to avoid crashing if key missing)
    auto get_range = [&](const std::string& key) {
        if (ranges.find(key) != ranges.end()) return ranges.at(key);
        return std::vector<double>{}; // Should not happen if python passes correctly
    };
    
    auto rsi_vals = get_range("rsi");
    auto wt_ch_vals = get_range("wt_ch");
    auto wt_avg_vals = get_range("wt_avg");
    auto cci_vals = get_range("cci");
    auto adx_len_vals = get_range("adx_len");
    auto adx_th_vals = get_range("adx_th");
    auto k_vals = get_range("k");
    auto lev_vals = get_range("lev");
    
    // New: ATR Multiplier Range
    std::vector<double> sl_mult_vals;
    if (ranges.find("sl_multiplier") != ranges.end()) {
        sl_mult_vals = ranges.at("sl_multiplier");
    } else {
        sl_mult_vals = {0.0}; 
    }

    // New: EMA Period Range
    std::vector<double> ema_vals;
    if (ranges.find("ema_period") != ranges.end()) {
        ema_vals = ranges.at("ema_period");
    } else {
        ema_vals = {(double)ema_period}; // Fallback to the single int passed
    }

    // New: Toggles (Use EMA Filter, Use ADX Filter)
    // 1.0 = True, 0.0 = False
    std::vector<double> use_ema_vals;
    if (ranges.find("use_ema_filter") != ranges.end()) use_ema_vals = ranges.at("use_ema_filter");
    else use_ema_vals = {1.0}; // Default ON

    std::vector<double> use_adx_vals;
    if (ranges.find("use_adx_filter") != ranges.end()) use_adx_vals = ranges.at("use_adx_filter");
    else use_adx_vals = {1.0}; // Default ON
    
    // Pre-allocate features matrix for KNN
    // Shape: [n_samples, 4] (RSI, WT1, CCI, ADX)
    std::vector<std::vector<double>> X(n, std::vector<double>(4));
    
    // [Optimization] Pre-compute all EMA vectors
    std::vector<std::vector<double>> all_ema_vecs;
    for (double period_d : ema_vals) {
        all_ema_vecs.push_back(indicators::ema(close, (int)period_d));
    }
    
    // --- LOOP START ---
    
    for (double r_len_d : rsi_vals) {
        int r_len = (int)r_len_d;
        rsi_vec = indicators::rsi(src, r_len);
        
        for (double wt_ch_d : wt_ch_vals) {
            int wt_ch = (int)wt_ch_d;
            for (double wt_avg_d : wt_avg_vals) {
                int wt_avg = (int)wt_avg_d;
                wt1_vec = indicators::wavetrend(src, wt_ch, wt_avg);
                
                for (double c_len_d : cci_vals) {
                    int c_len = (int)c_len_d;
                    cci_vec = indicators::cci(high, low, close, c_len);
                    
                    for (double a_len_d : adx_len_vals) {
                        int a_len = (int)a_len_d;
                        adx_vec = indicators::adx(high, low, close, a_len);
                        
                        // Construct X
                        for(size_t i=0; i<n; ++i) {
                            X[i][0] = rsi_vec[i];
                            X[i][1] = wt1_vec[i];
                            X[i][2] = cci_vec[i];
                            X[i][3] = adx_vec[i];
                        }
                        
                        // Prepare Train Data (exclude last)
                        std::vector<std::vector<double>> X_train(n-1);
                        std::vector<int> y_train(n-1);
                        for(size_t i=0; i<n-1; ++i) {
                            X_train[i] = X[i];
                            y_train[i] = target[i];
                        }
                        
                        // KNN Loop
                        for (double k_d : k_vals) {
                             int k_neighbors = (int)k_d;
                             FastKNN knn(k_neighbors);
                             knn.fit_internal(X_train, y_train);
                             
                             // Predict (Once)
                             auto preds = knn.predict_internal(X);
                             
                             
                             // Toggle: EMA Filter
                             for (double use_ema_d : use_ema_vals) {
                                 bool use_ema = (use_ema_d > 0.5);
                                 
                                 // Smart Loop: If filter OFF, only loop once (idx 0), ignore value
                                 // If filter ON, loop all periods
                                 size_t ema_loop_count = use_ema ? ema_vals.size() : 1;
                                 
                                 for (size_t e_idx = 0; e_idx < ema_loop_count; ++e_idx) {
                                     // Safe access: if use_ema is false but we loop once, ensure we don't crash if all_ema_vecs empty?
                                     // all_ema_vecs size matches ema_vals size.
                                     // If we loop once (idx=0), we use all_ema_vecs[0].
                                     // But if use_ema is false, we don't USE the vector value in logic.
                                     
                                     const std::vector<double>* p_ema_vec = nullptr;
                                     double current_ema_period = 0.0;
                                     
                                     if (!all_ema_vecs.empty()) {
                                         p_ema_vec = &all_ema_vecs[e_idx]; // Just point to something valid
                                         current_ema_period = ema_vals[e_idx];
                                     } else {
                                         // Should not happen if pre-computed correctly
                                         static std::vector<double> dummy(n, 0.0);
                                         p_ema_vec = &dummy;
                                     }
                                     
                                     // Toggle: ADX Filter
                                     for (double use_adx_d : use_adx_vals) {
                                         bool use_adx = (use_adx_d > 0.5);
                                         
                                         // Smart Loop: If filter OFF, loop once
                                         // If filter ON, loop all thresholds
                                         const std::vector<double>& eff_adx_ths = use_adx ? adx_th_vals : std::vector<double>{0.0};
                                         
                                         for (double adx_th : eff_adx_ths) {
                                             
                                             // Signal Generation
                                             std::vector<int> signals(n, 0);
                                             for(size_t i=0; i<n; ++i) {
                                                 bool long_cond = (preds[i] == 1);
                                                 bool short_cond = (preds[i] == -1);
                                                 
                                                 // Apply Filters conditionally
                                                 if (use_adx) {
                                                     if (adx_vec[i] <= adx_th) { long_cond = false; short_cond = false; }
                                                 }
                                                 
                                                 if (use_ema) {
                                                     // p_ema_vec is valid here
                                                     if (close[i] <= (*p_ema_vec)[i]) long_cond = false;
                                                     if (close[i] >= (*p_ema_vec)[i]) short_cond = false;
                                                 }
                                                 
                                                 if(long_cond) signals[i] = 1;
                                                 else if(short_cond) signals[i] = -1;
                                             }
                                             
                                             for (double lev_d : lev_vals) {
                                     int lev = (int)lev_d;
                                     
                                     // New Loop: SL Multiplier
                                     for (double sl_mult : sl_mult_vals) {
                                         
                                         // Pass ATR and SL Multiplier
                                         auto res = fast_backtest_internal(close, signals, atr_vec, lev, start_balance, sl_ratio, sl_mult, tp_ratio, fee);
                                         
                                         double score = -999.0;
                                         if (res.trades >= min_trades) {
                                             if (res.trades > max_trades) {
                                                 score = -999.0; // Penalty for Over-Trading
                                             } else {
                                                 // [Sharpe] Use Calculated Sharpe Ratio
                                                 score = res.sharpe;
                                                 
                                                 // Still Penalize High MDD
                                                 if (res.mdd > max_mdd) score = -999.0;
                                             }
                                         }
                                         
                                         if (score > min_top_score || top_results.size() < top_k) {
                                             OptimizationResult r;
                                             r.best_score = score;
                                             r.balance = res.balance;
                                             r.wins = res.wins;
                                             r.trades = res.trades;
                                             r.mdd = res.mdd;
                                             r.best_params["rsi_length"] = (double)r_len;
                                             r.best_params["wt_channel_len"] = (double)wt_ch;
                                             r.best_params["wt_avg_len"] = (double)wt_avg;
                                             r.best_params["cci_length"] = (double)c_len;
                                             r.best_params["adx_length"] = (double)a_len;
                                             r.best_params["adx_threshold"] = adx_th;
                                             r.best_params["neighbors"] = (double)k_neighbors;
                                             r.best_params["leverage"] = (double)lev;
                                             r.best_params["leverage"] = (double)lev;
                                             r.best_params["sl_multiplier"] = sl_mult;
                                             r.best_params["ema_period"] = current_ema_period; // [New]
                                             
                                             top_results.push_back(r);
                                             
                                             // Sort descending
                                             std::sort(top_results.begin(), top_results.end(), [](const OptimizationResult& a, const OptimizationResult& b) {
                                                 return a.best_score > b.best_score;
                                             });
                                             
                                             // Keep top K
                                             if (top_results.size() > top_k) {
                                                 top_results.pop_back(); // Remove lowest
                                             }
                                             
                                             // Update min threshold
                                             if (!top_results.empty()) {
                                                 min_top_score = top_results.back().best_score;
                                             }
                                         }
                                     } // End SL Mult Loop
                                 } // End Leverage Loop
                             } // End ADX Th Loop
                             } // End Use ADX Loop
                         } // End EMA Period Loop
                         } // End Use EMA Loop
                        } // End KNN Loop
                    }
                }
            }
        }
    }
    return top_results;
}

py::list optimize_grid_search_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::dict params_ranges,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    double sl_ratio, double tp_ratio, double fee,
    int min_trades, int max_trades, double max_mdd, int ema_period,
    int atr_period, double start_balance
) {
    // Convert arrays to vectors
    auto to_vec = [](py::array_t<double> arr) {
        auto buf = arr.request();
        double* ptr = static_cast<double*>(buf.ptr);
        return std::vector<double>(ptr, ptr + buf.size);
    };

    auto v_open = to_vec(open);
    auto v_high = to_vec(high);
    auto v_low = to_vec(low);
    auto v_close = to_vec(close);
    
    // Parse ranges (as Doubles)
    std::map<std::string, std::vector<double>> ranges;
    for (auto item : params_ranges) {
        std::string key = py::str(item.first);
        py::list val = item.second.cast<py::list>();
        ranges[key] = get_range_from_list(val);
    }
    
    // Release GIL for the heavy computation
    std::vector<OptimizationResult> results;
    {
        py::gil_scoped_release release;
        results = optimize_grid_search_internal(v_open, v_high, v_low, v_close, ranges, kernel_lookback, kernel_weight, kernel_lookback_mult, sl_ratio, tp_ratio, fee, min_trades, max_trades, max_mdd, ema_period, atr_period, start_balance);
    }
    
    py::list ret_list;
    for (const auto& res : results) {
        py::dict ret;
        ret["best_score"] = res.best_score;
        ret["balance"] = res.balance;
        ret["wins"] = res.wins;
        ret["trades"] = res.trades;
        ret["mdd"] = res.mdd;
        
        py::dict p;
        for(auto const& item : res.best_params) {
            std::string k = item.first;
            double v = item.second;
            if (k == "adx_threshold" || k == "sl_multiplier" || k == "leverage" || k == "ema_period" || k == "use_ema_filter" || k == "use_adx_filter") // floats
                p[k.c_str()] = v;
            else // integers usually
                p[k.c_str()] = (int)v; 
        }
        ret["best_params"] = p;
        ret_list.append(ret);
    }
    
    return ret_list;
}
