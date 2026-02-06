#pragma once
#include <vector>
#include <map>
#include <string>
#include <pybind11/numpy.h>

namespace py = pybind11;

struct OptimizationResult {
    double best_score;
    std::map<std::string, double> best_params;
    double balance;
    int wins;
    int trades;
    double mdd;
};

// Python wrapper
py::list optimize_grid_search_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::dict params_ranges,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    double sl_ratio, double tp_ratio, double fee,
    int min_trades, int max_trades, double max_mdd, int ema_period,
    int atr_period, double start_balance
);
