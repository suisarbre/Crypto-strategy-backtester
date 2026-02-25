#pragma once
#include <vector>
#include <map>
#include <string>
#include <pybind11/numpy.h>

namespace py = pybind11;

struct BacktestResult {
    double balance;
    int wins;
    int trades;
    double mdd;
    double sharpe;          // Legacy (kept for compatibility)
    double total_return;    // Total percentage return
    double sortino;         // Sortino Ratio (return / downside deviation)
    double calmar;          // Calmar Ratio (return / max drawdown)
    double profit_factor;   // Gross profit / Gross loss
};

// Python wrapper interface
py::dict fast_backtest_wrapper(
    py::array_t<double> prices, 
    py::array_t<int> signals, 
    py::array_t<int> exit_signals, // Bitmask: 1=LongExit, 2=ShortExit
    py::array_t<double> atr,
    int leverage, 
    double start_balance, 
    double sl_ratio, 
    double sl_multiplier,
    double tp_ratio, 
    double fee
);

// Pure C++ interface
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
);
