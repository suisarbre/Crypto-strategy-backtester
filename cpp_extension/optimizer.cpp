#include "optimizer.h"
#include "indicators.h"
#include "knn.h"
#include "backtester.h"
#include <iostream>
#include <numeric>
#include <algorithm>
#include <omp.h>

// Helper to extract vector from python list safely
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
    
    // Calculate src (OHLC/4)
    std::vector<double> src(n);
    for(size_t i=0; i<n; ++i) src[i] = (open[i] + high[i] + low[i] + close[i]) / 4.0;
    
    // Top K container
    int top_k = 20; 
    std::vector<OptimizationResult> top_results;
    double min_top_score = -999.0;

    // Indicators Containers (Thread-Local later)
    // Pre-calculated vectors for Filters
    std::vector<double> ema200_vec = indicators::ema(src, ema_period);
    std::vector<double> atr_vec = indicators::atr(high, low, close, atr_period);
    std::vector<double> chop_vec = indicators::choppiness(high, low, close, 14);
    
    // Kernel Calculation
    std::vector<bool> kernel_rising(n, true); 
    std::vector<bool> kernel_falling(n, true);
    auto kernel = indicators::rq_kernel(src, kernel_weight, kernel_lookback, kernel_lookback_mult); 
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
    
    // Range extraction
    auto get_range = [&](const std::string& key) {
        if (ranges.find(key) != ranges.end()) return ranges.at(key);
        return std::vector<double>{}; 
    };
    
    auto rsi_vals = get_range("rsi");
    auto wt_ch_vals = get_range("wt_ch");
    auto wt_avg_vals = get_range("wt_avg");
    auto cci_vals = get_range("cci");
    auto adx_len_vals = get_range("adx_len");
    auto adx_th_vals = get_range("adx_th");
    auto k_vals = get_range("k");
    auto lev_vals = get_range("lev");
    
    std::vector<double> sl_mult_vals;
    if (ranges.find("sl_multiplier") != ranges.end()) sl_mult_vals = ranges.at("sl_multiplier");
    else sl_mult_vals = {0.0}; 

    std::vector<double> ema_vals;
    if (ranges.find("ema_period") != ranges.end()) ema_vals = ranges.at("ema_period");
    else ema_vals = {(double)ema_period};

    std::vector<double> use_ema_vals;
    if (ranges.find("use_ema_filter") != ranges.end()) use_ema_vals = ranges.at("use_ema_filter");
    else use_ema_vals = {1.0};

    std::vector<double> use_adx_vals;
    if (ranges.find("use_adx_filter") != ranges.end()) use_adx_vals = ranges.at("use_adx_filter");
    else use_adx_vals = {1.0};

    std::vector<double> chop_th_vals;
    if (ranges.find("chop_threshold") != ranges.end()) chop_th_vals = ranges.at("chop_threshold");
    else chop_th_vals = {50.0};
    
    // Pre-compute all EMA vectors
    std::vector<std::vector<double>> all_ema_vecs;
    for (double period_d : ema_vals) {
        all_ema_vecs.push_back(indicators::ema(close, (int)period_d));
    }

    // Flatten Indicators
    struct IndicatorCombo {
        int rsi, wt_ch, wt_avg, cci, adx_len;
    };
    std::vector<IndicatorCombo> combos;
    combos.reserve(rsi_vals.size() * wt_ch_vals.size() * wt_avg_vals.size() * cci_vals.size() * adx_len_vals.size());

    for (double r : rsi_vals)
        for (double w_ch : wt_ch_vals)
            for (double w_avg : wt_avg_vals)
                for (double c : cci_vals)
                    for (double a : adx_len_vals)
                        combos.push_back({(int)r, (int)w_ch, (int)w_avg, (int)c, (int)a});

    // Flatten Filters (Optimized for Indexing)
    struct FilterCombo {
        double chop, adx_th, lev, sl_m;
        int ema_idx;
        bool u_ema, u_adx;
    };
    std::vector<FilterCombo> filter_combos;
    size_t filter_count_est = chop_th_vals.size() * adx_th_vals.size() * lev_vals.size() * sl_mult_vals.size() * ema_vals.size() * use_ema_vals.size() * use_adx_vals.size();
    filter_combos.reserve(filter_count_est);

    for (double chop : chop_th_vals)
        for (double adx_th : adx_th_vals)
            for (double lev : lev_vals)
                for (double sl : sl_mult_vals)
                    for (size_t e_idx=0; e_idx<ema_vals.size(); ++e_idx)
                        for (double u_ema : use_ema_vals)
                            for (double u_adx : use_adx_vals) {
                                filter_combos.push_back({
                                    chop, adx_th, lev, sl, 
                                    (int)e_idx, 
                                    (u_ema > 0.5), (u_adx > 0.5)
                                });
                            }

    // === HYBRID PARALLELIZATION ===

    // CASE A: Phase 2 (Single Indicator Combo) -> Parallelize Filters
    if (combos.size() == 1) {
        const auto& combo = combos[0];
        
        // 1. Calculate Indicators (Once)
        std::vector<double> rsi_vec_local = indicators::rsi(src, combo.rsi);
        std::vector<double> wt1_vec_local = indicators::wavetrend(src, combo.wt_ch, combo.wt_avg);
        std::vector<double> cci_vec_local = indicators::cci(high, low, close, combo.cci);
        std::vector<double> adx_vec_local = indicators::adx(high, low, close, combo.adx_len);
        
        std::vector<std::vector<double>> X_local(n, std::vector<double>(4));
        for(size_t j=0; j<n; ++j) {
            X_local[j][0] = rsi_vec_local[j]; X_local[j][1] = wt1_vec_local[j]; X_local[j][2] = cci_vec_local[j]; X_local[j][3] = adx_vec_local[j];
        }
        
        std::vector<std::vector<double>> X_train(n-1);
        std::vector<int> y_train(n-1);
        for(size_t j=0; j<n-1; ++j) { X_train[j] = X_local[j]; y_train[j] = target[j]; }

        // Loop K
        for (double k_d : k_vals) {
            int k = (int)k_d;
            FastKNN knn(k);
            knn.fit_internal(X_train, y_train);
            auto preds = knn.predict_internal(X_local);
            
            // Parallelize Filters
            #pragma omp parallel for schedule(dynamic)
            for (int f=0; f<(int)filter_combos.size(); ++f) {
                 const auto& f_combo = filter_combos[f];
                 
                std::vector<int> signals(n, 0);
                const auto& ema_vec = all_ema_vecs[f_combo.ema_idx]; // Shared Read-Only
                
                for(size_t t=200; t<n; ++t) {
                     int side = preds[t];
                     if (side == 0) continue;
                     bool ok = true;
                     
                     if (f_combo.u_adx && adx_vec_local[t] <= f_combo.adx_th) ok = false;
                     if (ok && chop_vec[t] >= f_combo.chop) ok = false; // Using global/pre-calc chop_vec
                     
                     if (ok && f_combo.u_ema) {
                         if (side == 1 && close[t] < ema_vec[t]) ok = false;
                         if (side == -1 && close[t] > ema_vec[t]) ok = false;
                     }
                     if (ok) {
                         if (side == 1 && !kernel_rising[t]) ok = false;
                         if (side == -1 && !kernel_falling[t]) ok = false;
                     }
                     if (ok) signals[t] = side;
                }
                
                // Assuming fast_backtest_internal is accessible via includes
                auto res = fast_backtest_internal(close, signals, atr_vec, (int)f_combo.lev, start_balance, sl_ratio, f_combo.sl_m, tp_ratio, fee);
                
                double score = -999.0;
                if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                    score = res.balance * (1.0 - (res.mdd * 1.5));
                }
                
                if (score > min_top_score) {
                    #pragma omp critical
                    {
                        if (score > min_top_score || top_results.size() < top_k) {
                            OptimizationResult r;
                            r.best_score = score;
                            r.balance = res.balance;
                            r.wins = res.wins;
                            r.trades = res.trades;
                            r.mdd = res.mdd;
                            r.best_params["rsi_length"] = (double)combo.rsi;
                            r.best_params["wt_channel_len"] = (double)combo.wt_ch;
                            r.best_params["wt_avg_len"] = (double)combo.wt_avg;
                            r.best_params["cci_length"] = (double)combo.cci;
                            r.best_params["adx_length"] = (double)combo.adx_len;
                            r.best_params["neighbors"] = (double)k;
                            r.best_params["chop_threshold"] = f_combo.chop;
                            r.best_params["adx_threshold"] = f_combo.adx_th;
                            r.best_params["leverage"] = f_combo.lev;
                            r.best_params["sl_multiplier"] = f_combo.sl_m;
                            r.best_params["ema_period"] = ema_vals[f_combo.ema_idx];
                            r.best_params["use_ema_filter"] = f_combo.u_ema ? 1.0 : 0.0;
                            r.best_params["use_adx_filter"] = f_combo.u_adx ? 1.0 : 0.0;
                            
                            top_results.push_back(r);
                            std::sort(top_results.begin(), top_results.end(), [](const OptimizationResult& a, const OptimizationResult& b){
                                return a.best_score > b.best_score;
                            });
                            if (top_results.size() > top_k) {
                                top_results.pop_back();
                                min_top_score = top_results.back().best_score;
                            } else {
                                if (!top_results.empty()) min_top_score = top_results.back().best_score;
                            }
                        }
                    }
                }
            } // End Parallel Filters
        } // End K Loop
    }
    // CASE B: Phase 1 (Many Indicators) -> Parallelize Indicators
    else {
        #pragma omp parallel for schedule(dynamic)
        for (int i = 0; i < (int)combos.size(); ++i) {
             const auto& combo = combos[i];
             
             // Re-calculate indicators
             std::vector<double> rsi_vec_local = indicators::rsi(src, combo.rsi);
             std::vector<double> wt1_vec_local = indicators::wavetrend(src, combo.wt_ch, combo.wt_avg);
             std::vector<double> cci_vec_local = indicators::cci(high, low, close, combo.cci);
             std::vector<double> adx_vec_local = indicators::adx(high, low, close, combo.adx_len);
             
             std::vector<std::vector<double>> X_local(n, std::vector<double>(4));
             for(size_t j=0; j<n; ++j) {
                 X_local[j][0] = rsi_vec_local[j]; X_local[j][1] = wt1_vec_local[j]; X_local[j][2] = cci_vec_local[j]; X_local[j][3] = adx_vec_local[j];
             }
             std::vector<std::vector<double>> X_train(n-1);
             std::vector<int> y_train(n-1);
             for(size_t j=0; j<n-1; ++j) { X_train[j] = X_local[j]; y_train[j] = target[j]; }

             for (double k_d : k_vals) {
                 int k = (int)k_d;
                 FastKNN knn(k);
                 knn.fit_internal(X_train, y_train);
                 auto preds = knn.predict_internal(X_local);
                 
                 // Serial Loop over Filters
                 for (const auto& f_combo : filter_combos) {
                    std::vector<int> signals(n, 0);
                    const auto& ema_vec = all_ema_vecs[f_combo.ema_idx];
                    
                    for(size_t t=200; t<n; ++t) {
                         int side = preds[t];
                         if (side == 0) continue;
                         bool ok = true;
                         if (f_combo.u_adx && adx_vec_local[t] <= f_combo.adx_th) ok = false;
                         if (ok && chop_vec[t] >= f_combo.chop) ok = false;
                         if (ok && f_combo.u_ema) {
                             if (side == 1 && close[t] < ema_vec[t]) ok = false;
                             if (side == -1 && close[t] > ema_vec[t]) ok = false;
                         }
                         if (ok) {
                             if (side == 1 && !kernel_rising[t]) ok = false;
                             if (side == -1 && !kernel_falling[t]) ok = false;
                         }
                         if (ok) signals[t] = side;
                    }
                    
                    auto res = fast_backtest_internal(close, signals, atr_vec, (int)f_combo.lev, start_balance, sl_ratio, f_combo.sl_m, tp_ratio, fee);
                    double score = -999.0;
                    if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                        score = res.balance * (1.0 - (res.mdd * 1.5));
                    }
                    
                    if (score > min_top_score) {
                        #pragma omp critical
                        {
                            if (score > min_top_score || top_results.size() < top_k) {
                                OptimizationResult r;
                                r.best_score = score;
                                r.balance = res.balance;
                                r.wins = res.wins;
                                r.trades = res.trades;
                                r.mdd = res.mdd;
                                r.best_params["rsi_length"] = (double)combo.rsi;
                                r.best_params["wt_channel_len"] = (double)combo.wt_ch;
                                r.best_params["wt_avg_len"] = (double)combo.wt_avg;
                                r.best_params["cci_length"] = (double)combo.cci;
                                r.best_params["adx_length"] = (double)combo.adx_len;
                                r.best_params["neighbors"] = (double)k;
                                r.best_params["chop_threshold"] = f_combo.chop;
                                r.best_params["adx_threshold"] = f_combo.adx_th;
                                r.best_params["leverage"] = f_combo.lev;
                                r.best_params["sl_multiplier"] = f_combo.sl_m;
                                r.best_params["ema_period"] = ema_vals[f_combo.ema_idx];
                                r.best_params["use_ema_filter"] = f_combo.u_ema ? 1.0 : 0.0;
                                r.best_params["use_adx_filter"] = f_combo.u_adx ? 1.0 : 0.0;
                                
                                top_results.push_back(r);
                                std::sort(top_results.begin(), top_results.end(), [](const OptimizationResult& a, const OptimizationResult& b){
                                    return a.best_score > b.best_score;
                                });
                                if (top_results.size() > top_k) {
                                    top_results.pop_back();
                                    min_top_score = top_results.back().best_score;
                                } else {
                                    if (!top_results.empty()) min_top_score = top_results.back().best_score;
                                }
                            }
                        }
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
    std::map<std::string, std::vector<double>> ranges;
    for (auto item : params_ranges) {
        std::string key = py::str(item.first);
        py::list val = item.second.cast<py::list>();
        ranges[key] = get_range_from_list(val);
    }
    
    // Explicit conversion
    std::vector<double> o_vec(open.data(), open.data() + open.size());
    std::vector<double> h_vec(high.data(), high.data() + high.size());
    std::vector<double> l_vec(low.data(), low.data() + low.size());
    std::vector<double> c_vec(close.data(), close.data() + close.size());
    
    auto results = optimize_grid_search_internal(o_vec, h_vec, l_vec, c_vec, ranges,
                                                 kernel_lookback, kernel_weight, kernel_lookback_mult,
                                                 sl_ratio, tp_ratio, fee, min_trades, max_trades, max_mdd, ema_period, atr_period, start_balance);
                                                 
    py::list py_results;
    for (const auto& r : results) {
        py::dict d;
        d["best_score"] = r.best_score;
        d["balance"] = r.balance;
        d["wins"] = r.wins;
        d["trades"] = r.trades;
        d["mdd"] = r.mdd;
        
        py::dict p;
        for (auto const& [k, v] : r.best_params) {
            p[k.c_str()] = v;
        }
        d["best_params"] = p;
        
        py_results.append(d);
    }
    return py_results;
}

// Replaced with empty (Module defined in bindings.cpp)
