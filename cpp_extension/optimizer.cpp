#include "optimizer.h"
#include "factory.h"
#include "indicators.h"
#include "knn.h"
#include "backtester.h"
#include "signal_evaluator.h"
#include <iostream>
#include <numeric>
#include <algorithm>
#include <cmath>
#include <random>
#ifdef _OPENMP
#include <omp.h>
#else
static inline int omp_get_thread_num() { return 0; }
#endif

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
    
    // [Benchmarking] Buy-and-Hold baseline return (per Financial Benchmarking Report)
    double baseline_return = (n > 1 && close[0] > 0) ? (close[n-1] - close[0]) / close[0] : 0.0;

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
    
    // Target for KNN: 4-bar lookback direction (matches original Lorentzian Classification)
    // y = close[0] > close[4] ? long : close[0] < close[4] ? short : neutral
    std::vector<int> target(n, 0);
    for(size_t i=4; i<n; ++i) {
        if(close[i] > close[i-4]) target[i] = 1;
        else if(close[i] < close[i-4]) target[i] = -1;
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

    // DEBUG: Print Search Space Size
    std::cout << "[DEBUG] Optimizer Search Space: " << combos.size() << " Ind Combos x " << filter_combos.size() << " Filter Combos" << std::endl;

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
                std::vector<int> exit_signals_empty(n, 0); // Empty for legacy optimizer
                auto res = fast_backtest_internal(close, signals, exit_signals_empty, atr_vec, (int)f_combo.lev, start_balance, sl_ratio, f_combo.sl_m, tp_ratio, fee);
                
                // [Benchmarking] Sortino-based fitness with MDD penalty (per Architecture Report)
                double score = -999.0;
                if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                    double base_score = res.sortino;
                    double mdd_penalty = 1.0;
                    if (res.mdd > 0.15) {
                        mdd_penalty = std::max(0.0, 1.0 - 3.0 * (res.mdd - 0.15));
                    }
                    score = base_score * mdd_penalty;
                    if (res.total_return < 0) score = std::min(score, res.total_return);
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
                            r.sortino = res.sortino;
                            r.calmar = res.calmar;
                            r.profit_factor = res.profit_factor;
                            r.total_return = res.total_return;
                            r.alpha = res.total_return - baseline_return;
                            r.baseline_return = baseline_return;
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
                    
                    std::vector<int> exit_signals(n, 0); // Empty for legacy optimizer
                    auto res = fast_backtest_internal(close, signals, exit_signals, atr_vec, (int)f_combo.lev, start_balance, sl_ratio, f_combo.sl_m, tp_ratio, fee);
                    // [Benchmarking] Sortino-based fitness with MDD penalty
                    double score = -999.0;
                    if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                        double base_score = res.sortino;
                        double mdd_penalty = 1.0;
                        if (res.mdd > 0.15) {
                            mdd_penalty = std::max(0.0, 1.0 - 3.0 * (res.mdd - 0.15));
                        }
                        score = base_score * mdd_penalty;
                        if (res.total_return < 0) score = std::min(score, res.total_return);
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
                                r.sortino = res.sortino;
                                r.calmar = res.calmar;
                                r.profit_factor = res.profit_factor;
                                r.total_return = res.total_return;
                                r.alpha = res.total_return - baseline_return;
                                r.baseline_return = baseline_return;
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

// 2. Generic Recursive Helper
void generate_permutations(
    const std::vector<std::string>& names,
    const std::vector<std::vector<double>>& values,
    std::vector<std::map<std::string, double>>& out_combos,
    std::map<std::string, double>& current,
    size_t depth
) {
    if (names.empty()) {
        out_combos.push_back(current); // Empty combo if no params
        return;
    }
    if (depth == names.size()) {
        out_combos.push_back(current);
        return;
    }
    
    const std::string& key = names[depth];
    const std::vector<double>& vals = values[depth];
    
    for (double v : vals) {
        current[key] = v;
        generate_permutations(names, values, out_combos, current, depth + 1);
    }
}

#include "signal_evaluator.h" // [NEW]

// ... (helpers)

// 3. Generic Optimizer Logic
std::vector<OptimizationResult> optimize_generic_internal(
    const std::vector<double>& open, 
    const std::vector<double>& high, 
    const std::vector<double>& low, 
    const std::vector<double>& close,
    const std::vector<std::string>& ind_names,
    const std::vector<std::vector<double>>& ind_values,
    const std::vector<std::string>& filt_names,
    const std::vector<std::vector<double>>& filt_values,
    const std::string& strategy_json, // [NEW]
    int min_trades, int max_trades, double max_mdd,
    double start_balance, double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult
) {
    size_t n = close.size();
    if (n < 200) return {};

    // [New] Init Evaluator
    SignalEvaluator evaluator(strategy_json);

    // [New] Parse Strategy to get Feature Defs
    auto j_strat = json::parse(strategy_json);
    std::vector<json> feature_defs;
    if (j_strat.contains("definitions") && j_strat["definitions"].contains("indicators")) {
        feature_defs = j_strat["definitions"]["indicators"].get<std::vector<json>>();
    }

    // Prepare Market Data for Factory
    MarketData market_data = {open, high, low, close};

    std::vector<double> src(n);
    for(size_t i=0; i<n; ++i) src[i] = (open[i] + high[i] + low[i] + close[i]) / 4.0;
    
    // Target for KNN: 4-bar lookback direction (matches original Lorentzian Classification)
    std::vector<int> target(n, 0);
    for(size_t i=4; i<n; ++i) {
        if(close[i] > close[i-4]) target[i] = 1;
        else if(close[i] < close[i-4]) target[i] = -1;
    }

    // 2. Generate Permutations
    std::vector<std::map<std::string, double>> ind_combos;
    std::map<std::string, double> curr_ind;
    generate_permutations(ind_names, ind_values, ind_combos, curr_ind, 0);
    
    std::vector<std::map<std::string, double>> filt_combos;
    std::map<std::string, double> curr_filt;
    generate_permutations(filt_names, filt_values, filt_combos, curr_filt, 0);

    // [Benchmarking] Buy-and-Hold baseline return (per Financial Benchmarking Report)
    double baseline_return = (n > 1 && close[0] > 0) ? (close[n-1] - close[0]) / close[0] : 0.0;

    // 3. Output Container
    int top_k = 20; 
    std::vector<OptimizationResult> top_results;
    double min_top_score = -999.0;
    
    // 4. Helper to resolve params
    auto resolve_param = [](const json& j_def, const std::string& key, const std::map<std::string, double>& params) -> double {
        if (!j_def.contains(key)) return 0.0;
        auto val = j_def[key];
        if (val.is_number()) return val.get<double>();
        if (val.is_string()) {
            std::string p_name = val.get<std::string>();
            if (params.count(p_name)) return params.at(p_name);
        }
        return 0.0; // Fail safe
    };

    // Helper to extract string param (e.g. source)
    auto resolve_string = [](const json& j_def, const std::string& key) -> std::string {
         if (j_def.contains(key) && j_def[key].is_string()) return j_def[key].get<std::string>();
         return "close";
    };

    // === HYBRID PARALLELIZATION REFACTORED ===
    
    // CASE A: Phase 2 (Single Indicator Combo) -> Parallelize Filters
    if (ind_combos.size() == 1) {
        const auto& ind_params = ind_combos[0];
        
        // A. Calculated Indicators (Generic Loop)
        std::map<std::string, std::vector<double>> features_storage; // Owns data
        std::map<std::string, const std::vector<double>*> ind_map;   // Pointers
        
        // Pre-populate standard sources
        ind_map["close"] = &close;
        ind_map["open"] = &open;
        ind_map["high"] = &high;
        ind_map["low"] = &low;
        
        // ML Features
        std::vector<std::string> ml_feature_names;
        
        for (const auto& feat : feature_defs) {
            std::string name = feat["name"];
            std::string type = feat["type"];
            std::string source = resolve_string(feat, "source");
            
            // Build params for this feature
            std::map<std::string, double> f_params;
            for (auto& el : feat.items()) {
                if (el.key() != "name" && el.key() != "type" && el.key() != "source" && el.key() != "ml_feature") {
                     // Check if value maps to optimization param
                     f_params[el.key()] = resolve_param(feat, el.key(), ind_params);
                }
            }
            
            // Compute
            // Note: Some features might depend on "filter" params (like EMA period).
            // Rules: 
            // - If param is in 'ind_params' (Phase 1/Fixed), we compute here.
            // - If param is ONLY in 'filt_params' (Phase 2 grid), we MUST compute inside loop.
            // For Phase 2, ind_params are FIXED. filt_params vary.
            // If a feature depends on a varying filt param, we should probably skip it here?
            // "ema_filter" uses "ema_period", which is often in filt_params.
            // If resolve_param returns 0.0 because it's missing from ind_params... that's bad.
            // FIX: If param missing in ind_params, assume it's 0.0 or check filt_names?
            // "ema_period" is in filt_combos.
            
            // Heuristic: If ANY param required by feature is missing from ind_params, defer computation?
            // Or just compute everything here using ind_params (which might include defaults or be 0).
            // Current Logic: Optimizer passes ALL ranges. ind_params has indicator ranges. filt_params has filter ranges.
            // If "ema_period" is in filt_params, it is NOT in ind_params.
            // So resolve_param returns 0.
            // If we compute EMA(0), we get garbage.
            
            // Filter Loop Check:
            bool depends_on_filter = false;
            for (auto& el : feat.items()) {
                if (el.value().is_string()) {
                    std::string p_name = el.value().get<std::string>();
                    // Check if this param name is in filt_names
                    for(const auto& fn : filt_names) if(fn == p_name) depends_on_filter = true;
                }
            }
            
            if (depends_on_filter) {
                // Must compute inside loop
                continue; 
            }
            
            // Compute Now
            features_storage[name] = IndicatorFactory::compute(type, source, f_params, market_data);
            ind_map[name] = &features_storage[name];
            
            if (feat.contains("ml_feature") && feat["ml_feature"].get<bool>() == true) {
                ml_feature_names.push_back(name);
            }
        }
        
        // Train ML (If features exist)
        // We need 'neighbors' param. Is it in ind_params? Yes.
        // Or generic 'k'?
        // The strategies.json doesn't specify ML model params yet.
        // We assume "neighbors" is in ind_params if we do KNN.
        std::vector<int> preds(n, 0);
        
        if (!ml_feature_names.empty() && ind_params.count("neighbors")) {
            size_t n_feats = ml_feature_names.size();
            // Build X matrix
            std::vector<std::vector<double>> X_local(n, std::vector<double>(n_feats));
            for(size_t j=0; j<n; ++j) {
                for(size_t k=0; k<n_feats; ++k) {
                    X_local[j][k] = (*ind_map[ml_feature_names[k]])[j];
                }
            }
            std::vector<std::vector<double>> X_train(n-1);
            std::vector<int> y_train(n-1);
            for(size_t j=0; j<n-1; ++j) { X_train[j] = X_local[j]; y_train[j] = target[j]; }
            
            int k = (int)ind_params.at("neighbors");
            FastKNN knn(k);
            knn.fit_internal(X_train, y_train);
            preds = knn.predict_internal(X_local);
        }

        // B. Parallel Loop over Filters
        #pragma omp parallel for schedule(dynamic)
        for (int f = 0; f < (int)filt_combos.size(); ++f) {
            const auto& filt_params = filt_combos[f];
            
            // Copy ind_map for this thread (lightweight pointers)
            auto thread_ind_map = ind_map; 
            
            // 1. Compute Filter-Dependent Indicators (e.g. EMA Filter)
            std::vector<std::vector<double>> temp_features; // Keep alive during scope
            
            for (const auto& feat : feature_defs) {
                std::string name = feat["name"];
                if (thread_ind_map.count(name)) continue; // Already computed

                std::string type = feat["type"];
                std::string source = resolve_string(feat, "source");
                
                std::map<std::string, double> f_params;
                for (auto& el : feat.items()) {
                    if (el.key() != "name" && el.key() != "type" && el.key() != "source" && el.key() != "ml_feature") {
                         // Check ind_params THEN filt_params
                         double val = 0.0;
                         if (el.value().is_string()) {
                             std::string p = el.value().get<std::string>();
                             if (ind_params.count(p)) val = ind_params.at(p);
                             else if (filt_params.count(p)) val = filt_params.at(p);
                         } else if (el.value().is_number()) {
                             val = el.value().get<double>();
                         }
                         f_params[el.key()] = val;
                    }
                }
                
                temp_features.push_back(IndicatorFactory::compute(type, source, f_params, market_data));
                thread_ind_map[name] = &temp_features.back();
            }
            
            // Merge params
            std::map<std::string, double> all_params = ind_params;
            for(auto const& [k,v] : filt_params) all_params[k] = v;
            
            // 2. Evaluate Signals
            std::vector<int> signals(n, 0);
            std::vector<int> exit_signals(n, 0);

            for(size_t i_time=200; i_time<n; ++i_time) {
                int knn_sig = preds[i_time]; // Use pre-computed ML
                signals[i_time] = evaluator.evaluate(i_time, thread_ind_map, all_params, knn_sig);
                exit_signals[i_time] = evaluator.evaluate_exit(i_time, thread_ind_map, all_params);
            }
            
            // 3. Backtest
            auto res = fast_backtest_internal(
                close, signals, exit_signals, 
                // We need ATR vector for backtester? 
                // Legacy: passed 'atr_vec'. New: pass it from map if exists, else compute?
                // fast_backtest_internal signature from 'backtester.h':
                // (close, sig, exit, atr, lev, start_bal, sl_ratio, sl_mult, tp_ratio, fee)
                // We MUST find 'atr' in map.
                (thread_ind_map.count("atr") ? *thread_ind_map.at("atr") : std::vector<double>(n,0)),
                (int)all_params["leverage"],
                start_balance,
                (all_params.count("sl_ratio") ? all_params.at("sl_ratio") : sl_ratio),
                (all_params.count("sl_multiplier") ? all_params.at("sl_multiplier") : 3.0),
                (all_params.count("tp_ratio") ? all_params.at("tp_ratio") : tp_ratio),
                fee
            );
            
            // [Benchmarking] Sortino-based fitness with MDD penalty (per Architecture Report)
            double score = -999.0;
            if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                double base_score = res.sortino;
                double mdd_penalty = 1.0;
                if (res.mdd > 0.15) {
                    mdd_penalty = std::max(0.0, 1.0 - 3.0 * (res.mdd - 0.15));
                }
                score = base_score * mdd_penalty;
                if (res.total_return < 0) score = std::min(score, res.total_return);
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
                        r.sortino = res.sortino;
                        r.calmar = res.calmar;
                        r.profit_factor = res.profit_factor;
                        r.total_return = res.total_return;
                        r.alpha = res.total_return - baseline_return;
                        r.baseline_return = baseline_return;
                        r.best_params = all_params;
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
    // CASE B: Phase 1 (Many Indicators) -> Parallelize Indicators
    else {
        #pragma omp parallel for schedule(dynamic)
        for (int i = 0; i < (int)ind_combos.size(); ++i) {
            const auto& ind_params = ind_combos[i];
            
            // Thread-local storage
            std::map<std::string, std::vector<double>> features_storage; 
            std::map<std::string, const std::vector<double>*> thread_ind_map;
            
            thread_ind_map["close"] = &close;
            thread_ind_map["open"] = &open;
            thread_ind_map["high"] = &high;
            thread_ind_map["low"] = &low;
            
             std::vector<std::string> ml_feature_names;

             // Compute Features
             for (const auto& feat : feature_defs) {
                std::string name = feat["name"];
                std::string type = feat["type"];
                std::string source = resolve_string(feat, "source");
                
                std::map<std::string, double> f_params;
                for (auto& el : feat.items()) {
                    if (el.key() != "name" && el.key() != "type" && el.key() != "source" && el.key() != "ml_feature") {
                         f_params[el.key()] = resolve_param(feat, el.key(), ind_params);
                    }
                }
                
                // Assuming Phase 1 mainly iterates indicators, so no filter dependency here?
                // Or filter params are default.
                // We use ind_params.
                
                features_storage[name] = IndicatorFactory::compute(type, source, f_params, market_data);
                thread_ind_map[name] = &features_storage[name];
                
                if (feat.contains("ml_feature") && feat["ml_feature"].get<bool>() == true) {
                    ml_feature_names.push_back(name);
                }
            }
            
            // Train ML
            std::vector<int> preds(n, 0);
            if (!ml_feature_names.empty() && ind_params.count("neighbors")) {
                 size_t n_feats = ml_feature_names.size();
                std::vector<std::vector<double>> X_local(n, std::vector<double>(n_feats));
                for(size_t j=0; j<n; ++j) {
                    for(size_t k=0; k<n_feats; ++k) X_local[j][k] = (*thread_ind_map[ml_feature_names[k]])[j];
                }
                std::vector<std::vector<double>> X_train(n-1);
                std::vector<int> y_train(n-1);
                for(size_t j=0; j<n-1; ++j) { X_train[j] = X_local[j]; y_train[j] = target[j]; }
                
                int k = (int)ind_params.at("neighbors");
                FastKNN knn(k);
                knn.fit_internal(X_train, y_train);
                preds = knn.predict_internal(X_local);
            }
            
            // Process Filters
            for (const auto& filt_params : filt_combos) {
                 // Note: In Phase 1, filters are usually SINGLE (default) combo.
                 // We don't re-compute features here assuming filters don't change feature params.
                 // If they did, we'd need re-compute. Assuming they don't for Phase 1.
                 
                 std::map<std::string, double> all_params = ind_params;
                 for(auto const& [k,v] : filt_params) all_params[k] = v;
                 
                 std::vector<int> signals(n, 0);
                 std::vector<int> exit_signals(n, 0);
                 
                 for(size_t i_time=200; i_time<n; ++i_time) {
                    int knn_sig = preds[i_time];
                    signals[i_time] = evaluator.evaluate(i_time, thread_ind_map, all_params, knn_sig);
                    exit_signals[i_time] = evaluator.evaluate_exit(i_time, thread_ind_map, all_params);
                }
                
                auto res = fast_backtest_internal(
                    close, signals, exit_signals, 
                    (thread_ind_map.count("atr") ? *thread_ind_map.at("atr") : std::vector<double>(n,0)),
                    (int)all_params["leverage"],
                    start_balance,
                    (all_params.count("sl_ratio") ? all_params.at("sl_ratio") : sl_ratio),
                    (all_params.count("sl_multiplier") ? all_params.at("sl_multiplier") : 3.0),
                    (all_params.count("tp_ratio") ? all_params.at("tp_ratio") : tp_ratio),
                    fee
                );

                // [Benchmarking] Sortino-based fitness with MDD penalty
                double score = -999.0;
                if (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd) {
                    double base_score = res.sortino;
                    double mdd_penalty = 1.0;
                    if (res.mdd > 0.15) {
                        mdd_penalty = std::max(0.0, 1.0 - 3.0 * (res.mdd - 0.15));
                    }
                    score = base_score * mdd_penalty;
                    if (res.total_return < 0) score = std::min(score, res.total_return);
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
                            r.sortino = res.sortino;
                            r.calmar = res.calmar;
                            r.profit_factor = res.profit_factor;
                            r.total_return = res.total_return;
                            r.alpha = res.total_return - baseline_return;
                            r.baseline_return = baseline_return;
                            r.best_params = all_params;
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
    
    return top_results;
}

// Wrapper for Python
py::list optimize_generic_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::list ind_names, py::list ind_values,
    py::list filt_names, py::list filt_values,
    std::string strategy_json, // [NEW]
    int min_trades, int max_trades, double max_mdd, double start_balance,
    double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult
) {
    if (open.size() != close.size()) return py::list();
    
    std::vector<std::string> i_names;
    for(auto item : ind_names) i_names.push_back(py::str(item));
    
    std::vector<std::vector<double>> i_vals;
    for(auto item : ind_values) i_vals.push_back(get_range_from_list(item.cast<py::list>()));
    
    std::vector<std::string> f_names;
    for(auto item : filt_names) f_names.push_back(py::str(item));
    
    std::vector<std::vector<double>> f_vals;
    for(auto item : filt_values) f_vals.push_back(get_range_from_list(item.cast<py::list>()));
    
    // Convert arrays
    std::vector<double> o_vec(open.data(), open.data() + open.size());
    std::vector<double> h_vec(high.data(), high.data() + high.size());
    std::vector<double> l_vec(low.data(), low.data() + low.size());
    std::vector<double> c_vec(close.data(), close.data() + close.size());
    
    // [Fix] Release GIL for heavy computation
    std::vector<OptimizationResult> results;
    {
        py::gil_scoped_release release; 
        results = optimize_generic_internal(
            o_vec, h_vec, l_vec, c_vec, 
            i_names, i_vals, f_names, f_vals,
            strategy_json, 
            min_trades, max_trades, max_mdd, start_balance, fee, tp_ratio, sl_ratio,
            kernel_lookback, kernel_weight, kernel_lookback_mult
        );
    }
    
    py::list py_results;
    for (const auto& r : results) {
        py::dict d;
        d["best_score"] = r.best_score;
        d["balance"] = r.balance;
        d["wins"] = r.wins;
        d["trades"] = r.trades;
        d["mdd"] = r.mdd;
        // [Benchmarking] Risk-adjusted metrics (per Financial Benchmarking Report)
        d["sortino"] = r.sortino;
        d["calmar"] = r.calmar;
        d["profit_factor"] = r.profit_factor;
        d["total_return"] = r.total_return;
        d["alpha"] = r.alpha;
        d["baseline_return"] = r.baseline_return;
        py::dict p;
        for (auto const& [k, v] : r.best_params) p[k.c_str()] = v;
        d["best_params"] = p;
        py_results.append(d);
    }
    return py_results;
}


// ============================================================================
// [PSO] Particle Swarm Optimization (per Architecture Report)
// Replaces exhaustive grid search with intelligent swarm-based parameter discovery.
// Each particle explores the parameter space; particles are evaluated in parallel.
// ============================================================================

std::vector<OptimizationResult> optimize_pso_internal(
    const std::vector<double>& open,
    const std::vector<double>& high,
    const std::vector<double>& low,
    const std::vector<double>& close,
    const std::vector<std::string>& param_names,
    const std::vector<double>& param_mins,
    const std::vector<double>& param_maxs,
    const std::vector<double>& param_defaults,
    const std::string& strategy_json,
    int min_trades, int max_trades, double max_mdd, double start_balance,
    double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    int swarm_size, int max_iterations
) {
    size_t n = close.size();
    int n_dims = (int)param_names.size();
    if (n < 200 || n_dims == 0) return {};

    // [Benchmarking] Buy-and-Hold baseline
    double baseline_return = (n > 1 && close[0] > 0) ? (close[n-1] - close[0]) / close[0] : 0.0;

    // Parse strategy JSON
    json strategy;
    try {
        strategy = json::parse(strategy_json);
    } catch (...) {
        return {};
    }

    json feature_defs = strategy.value("definitions", json::object()).value("indicators", json::array());

    // Market data for IndicatorFactory
    MarketData market_data;
    market_data.open = open;
    market_data.high = high;
    market_data.low = low;
    market_data.close = close;

    // Target for KNN: 4-bar lookback direction (matches original Lorentzian Classification)
    // y = close[0] > close[4] ? long : close[0] < close[4] ? short : neutral
    std::vector<int> target(n, 0);
    for (size_t i = 4; i < n; ++i) {
        if (close[i] > close[i - 4]) target[i] = 1;
        else if (close[i] < close[i - 4]) target[i] = -1;
    }

    // Kernel pre-computation
    std::vector<double> src(n);
    for (size_t i = 0; i < n; ++i) src[i] = (open[i] + high[i] + low[i] + close[i]) / 4.0;
    auto kernel = indicators::rq_kernel(src, kernel_weight, kernel_lookback, kernel_lookback_mult);

    // Helper: resolve parameter from JSON definition + param map
    auto resolve_param = [](const json& j_def, const std::string& key, const std::map<std::string, double>& params) -> double {
        if (!j_def.contains(key)) return 0.0;
        auto val = j_def[key];
        if (val.is_number()) return val.get<double>();
        if (val.is_string()) {
            std::string pname = val.get<std::string>();
            if (params.count(pname)) return params.at(pname);
        }
        return 0.0;
    };
    auto resolve_string = [](const json& j_def, const std::string& key) -> std::string {
        if (!j_def.contains(key)) return "close";
        auto val = j_def[key];
        if (val.is_string()) return val.get<std::string>();
        return "close";
    };

    // PSO Hyperparameters
    double w = 0.7;    // Inertia weight
    double c1 = 1.5;   // Cognitive coefficient (personal best attraction)
    double c2 = 2.0;   // Social coefficient (global best attraction)
    double w_min = 0.4; // Minimum inertia (linearly decreasing)

    // Check if we have valid defaults for seeding
    bool has_defaults = ((int)param_defaults.size() == n_dims);

    // Initialize swarm
    std::vector<Particle> swarm(swarm_size);
    std::vector<double> global_best_pos(n_dims);
    double global_best_fitness = -1e18;

    // Thread-safe RNG initialization
    std::random_device rd;
    std::mt19937 gen(rd());

    // Seed strategy: ~25% of particles near defaults, rest random
    int n_seeded = has_defaults ? std::max(1, swarm_size / 4) : 0;

    for (int p = 0; p < swarm_size; ++p) {
        swarm[p].position.resize(n_dims);
        swarm[p].velocity.resize(n_dims);
        swarm[p].best_position.resize(n_dims);
        swarm[p].best_fitness = -1e18;

        for (int d = 0; d < n_dims; ++d) {
            double range = param_maxs[d] - param_mins[d];
            if (p < n_seeded && has_defaults) {
                // Seed near defaults: particle 0 = exact defaults, others = perturbation
                double def_val = param_defaults[d];
                def_val = std::max(param_mins[d], std::min(param_maxs[d], def_val));
                if (p == 0) {
                    swarm[p].position[d] = def_val;
                } else {
                    // Gaussian perturbation around default (σ = 15% of range)
                    double sigma = range * 0.15;
                    std::normal_distribution<double> ndist(def_val, sigma);
                    double val = ndist(gen);
                    swarm[p].position[d] = std::max(param_mins[d], std::min(param_maxs[d], val));
                }
            } else {
                std::uniform_real_distribution<double> dist(param_mins[d], param_maxs[d]);
                swarm[p].position[d] = dist(gen);
            }
            std::uniform_real_distribution<double> vel_dist(-range * 0.1, range * 0.1);
            swarm[p].velocity[d] = vel_dist(gen);
            swarm[p].best_position[d] = swarm[p].position[d];
        }
    }

    // Top results accumulator
    int top_k = 20;
    std::vector<OptimizationResult> top_results;

    // PSO Main Loop
    for (int iter = 0; iter < max_iterations; ++iter) {
        // Linearly decreasing inertia
        double current_w = w - (w - w_min) * ((double)iter / max_iterations);

        // Evaluate all particles in parallel
        #pragma omp parallel
        {
            // Thread-local RNG
            std::mt19937 thread_gen(rd() + omp_get_thread_num());

            #pragma omp for schedule(dynamic)
            for (int p = 0; p < swarm_size; ++p) {
                // Convert position to params map (round integers)
                std::map<std::string, double> params;
                for (int d = 0; d < n_dims; ++d) {
                    double val = swarm[p].position[d];
                    // Clamp to bounds
                    val = std::max(param_mins[d], std::min(param_maxs[d], val));
                    // Round to integer for typical strategy params
                    // (leverage, lengths, neighbors are integers; ratios are floats)
                    if (param_maxs[d] - param_mins[d] >= 2.0 && param_mins[d] >= 1.0) {
                        val = std::round(val);
                    }
                    params[param_names[d]] = val;
                    swarm[p].position[d] = val; // Store clamped value
                }

                // === Evaluate: Compute indicators, signals, backtest ===
                std::map<std::string, std::vector<double>> features_storage;
                std::map<std::string, const std::vector<double>*> ind_map;
                ind_map["close"] = &close;
                ind_map["open"] = &open;
                ind_map["high"] = &high;
                ind_map["low"] = &low;

                std::vector<std::string> ml_feature_names;

                for (const auto& feat : feature_defs) {
                    std::string name = feat["name"];
                    std::string type = feat["type"];
                    std::string source = resolve_string(feat, "source");

                    std::map<std::string, double> f_params;
                    for (auto& el : feat.items()) {
                        if (el.key() != "name" && el.key() != "type" && el.key() != "source" && el.key() != "ml_feature") {
                            f_params[el.key()] = resolve_param(feat, el.key(), params);
                        }
                    }

                    features_storage[name] = IndicatorFactory::compute(type, source, f_params, market_data);
                    ind_map[name] = &features_storage[name];

                    if (feat.contains("ml_feature") && feat["ml_feature"].get<bool>()) {
                        ml_feature_names.push_back(name);
                    }
                }

                // Train KNN
                std::vector<int> preds(n, 0);
                if (!ml_feature_names.empty() && params.count("neighbors") && params.at("neighbors") >= 1) {
                    size_t n_feats = ml_feature_names.size();
                    std::vector<std::vector<double>> X_local(n, std::vector<double>(n_feats));
                    for (size_t j = 0; j < n; ++j) {
                        for (size_t kk = 0; kk < n_feats; ++kk) {
                            X_local[j][kk] = (*ind_map[ml_feature_names[kk]])[j];
                        }
                    }
                    std::vector<std::vector<double>> X_train(n - 1);
                    std::vector<int> y_train(n - 1);
                    for (size_t j = 0; j < n - 1; ++j) {
                        X_train[j] = X_local[j];
                        y_train[j] = target[j];
                    }
                    int k_val = (int)params.at("neighbors");
                    FastKNN knn(k_val);
                    knn.fit_internal(X_train, y_train);
                    preds = knn.predict_internal(X_local);
                }

                // Evaluate signals
                SignalEvaluator evaluator(strategy_json);
                std::vector<int> signals(n, 0);
                std::vector<int> exit_signals(n, 0);
                for (size_t i_time = 200; i_time < n; ++i_time) {
                    signals[i_time] = evaluator.evaluate(i_time, ind_map, params, preds[i_time]);
                    exit_signals[i_time] = evaluator.evaluate_exit(i_time, ind_map, params);
                }

                // Backtest
                auto res = fast_backtest_internal(
                    close, signals, exit_signals,
                    (ind_map.count("atr") ? *ind_map.at("atr") : std::vector<double>(n, 0)),
                    (int)(params.count("leverage") ? params.at("leverage") : 1),
                    start_balance,
                    (params.count("sl_ratio") ? params.at("sl_ratio") : sl_ratio),
                    (params.count("sl_multiplier") ? params.at("sl_multiplier") : 3.0),
                    (params.count("tp_ratio") ? params.at("tp_ratio") : tp_ratio),
                    fee
                );

                // Sortino-based fitness with soft penalty for constraint violations
                // Instead of hard -1e18 gate, use penalty functions so PSO can
                // navigate toward feasible regions in high-dimensional spaces
                double fitness = -1e18;
                bool feasible = (res.trades >= min_trades && res.trades <= max_trades && res.mdd <= max_mdd);

                if (res.trades > 0) {
                    double base_score = res.sortino;
                    double mdd_penalty = 1.0;
                    if (res.mdd > 0.15) {
                        mdd_penalty = std::max(0.0, 1.0 - 3.0 * (res.mdd - 0.15));
                    }
                    fitness = base_score * mdd_penalty;
                    if (res.total_return < 0) fitness = std::min(fitness, res.total_return);

                    // Soft penalties for constraint violations (guide particles toward feasibility)
                    if (!feasible) {
                        double constraint_penalty = 0.0;
                        if (res.trades < min_trades) {
                            constraint_penalty += 2.0 * (double)(min_trades - res.trades) / min_trades;
                        }
                        if (res.trades > max_trades) {
                            constraint_penalty += 2.0 * (double)(res.trades - max_trades) / max_trades;
                        }
                        if (res.mdd > max_mdd) {
                            constraint_penalty += 5.0 * (res.mdd - max_mdd) / max_mdd;
                        }
                        // Penalize but keep finite — allows PSO convergence
                        fitness = fitness - constraint_penalty - 10.0;
                    }
                } else {
                    // No trades at all — use a small negative based on how far from generating trades
                    fitness = -100.0;
                }

                // Update personal best
                if (fitness > swarm[p].best_fitness) {
                    swarm[p].best_fitness = fitness;
                    swarm[p].best_position = swarm[p].position;
                }

                // Track top results (only feasible ones for final output)
                if (feasible && fitness > -999.0) {
                    #pragma omp critical
                    {
                        OptimizationResult r;
                        r.best_score = fitness;
                        r.balance = res.balance;
                        r.wins = res.wins;
                        r.trades = res.trades;
                        r.mdd = res.mdd;
                        r.sortino = res.sortino;
                        r.calmar = res.calmar;
                        r.profit_factor = res.profit_factor;
                        r.total_return = res.total_return;
                        r.alpha = res.total_return - baseline_return;
                        r.baseline_return = baseline_return;
                        r.best_params = params;
                        top_results.push_back(r);
                        std::sort(top_results.begin(), top_results.end(),
                            [](const OptimizationResult& a, const OptimizationResult& b) {
                                return a.best_score > b.best_score;
                            });
                        if ((int)top_results.size() > top_k) top_results.pop_back();
                    }
                }

                // Update global best (across ALL particles, feasible or not)
                // This guides the swarm even when no feasible result exists yet
                #pragma omp critical
                {
                    if (fitness > global_best_fitness) {
                        global_best_fitness = fitness;
                        global_best_pos = swarm[p].position;
                    }
                }
            } // end parallel for

            // Update velocities and positions (sequential per thread group)
            #pragma omp for schedule(static)
            for (int p = 0; p < swarm_size; ++p) {
                std::uniform_real_distribution<double> dist01(0.0, 1.0);
                for (int d = 0; d < n_dims; ++d) {
                    double r1 = dist01(thread_gen);
                    double r2 = dist01(thread_gen);

                    swarm[p].velocity[d] = current_w * swarm[p].velocity[d]
                        + c1 * r1 * (swarm[p].best_position[d] - swarm[p].position[d])
                        + c2 * r2 * (global_best_pos[d] - swarm[p].position[d]);

                    // Velocity clamping
                    double max_vel = (param_maxs[d] - param_mins[d]) * 0.3;
                    swarm[p].velocity[d] = std::max(-max_vel, std::min(max_vel, swarm[p].velocity[d]));

                    swarm[p].position[d] += swarm[p].velocity[d];

                    // Boundary clamping
                    swarm[p].position[d] = std::max(param_mins[d], std::min(param_maxs[d], swarm[p].position[d]));
                }
            }
        } // end parallel
    } // end PSO iterations

    return top_results;
}


// PSO Python Wrapper
py::list optimize_pso_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::list param_names_py, py::list param_mins_py, py::list param_maxs_py,
    py::list param_defaults_py,
    std::string strategy_json,
    int min_trades, int max_trades, double max_mdd, double start_balance,
    double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    int swarm_size, int max_iterations
) {
    if (open.size() != close.size()) return py::list();

    std::vector<std::string> names;
    for (auto item : param_names_py) names.push_back(py::str(item));

    std::vector<double> mins;
    for (auto item : param_mins_py) mins.push_back(item.cast<double>());

    std::vector<double> maxs;
    for (auto item : param_maxs_py) maxs.push_back(item.cast<double>());

    std::vector<double> defaults;
    for (auto item : param_defaults_py) defaults.push_back(item.cast<double>());

    std::vector<double> o_vec(open.data(), open.data() + open.size());
    std::vector<double> h_vec(high.data(), high.data() + high.size());
    std::vector<double> l_vec(low.data(), low.data() + low.size());
    std::vector<double> c_vec(close.data(), close.data() + close.size());

    std::vector<OptimizationResult> results;
    {
        py::gil_scoped_release release;
        results = optimize_pso_internal(
            o_vec, h_vec, l_vec, c_vec,
            names, mins, maxs, defaults,
            strategy_json,
            min_trades, max_trades, max_mdd, start_balance, fee, tp_ratio, sl_ratio,
            kernel_lookback, kernel_weight, kernel_lookback_mult,
            swarm_size, max_iterations
        );
    }

    py::list py_results;
    for (const auto& r : results) {
        py::dict d;
        d["best_score"] = r.best_score;
        d["balance"] = r.balance;
        d["wins"] = r.wins;
        d["trades"] = r.trades;
        d["mdd"] = r.mdd;
        d["sortino"] = r.sortino;
        d["calmar"] = r.calmar;
        d["profit_factor"] = r.profit_factor;
        d["total_return"] = r.total_return;
        d["alpha"] = r.alpha;
        d["baseline_return"] = r.baseline_return;
        py::dict p;
        for (auto const& [k, v] : r.best_params) p[k.c_str()] = v;
        d["best_params"] = p;
        py_results.append(d);
    }
    return py_results;
}

// Module definition removed (moved to bindings.cpp)
