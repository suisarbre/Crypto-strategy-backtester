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
    // [Benchmarking] Risk-adjusted metrics (per Architecture & Benchmarking Reports)
    double sortino;          // Sortino Ratio
    double calmar;           // Calmar Ratio
    double profit_factor;    // Gross Profit / Gross Loss
    double total_return;     // Strategy total percentage return
    double alpha;            // Outperformance vs Buy-and-Hold baseline
    double baseline_return;  // Buy-and-Hold return for the dataset
};

// [PSO] Particle for Particle Swarm Optimization
struct Particle {
    std::vector<double> position;       // Current parameter values
    std::vector<double> velocity;       // Current velocity vector
    double best_fitness;                // Personal best fitness
    std::vector<double> best_position;  // Position that gave personal best
};

// Python wrapper - Legacy Grid Search
py::list optimize_grid_search_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::dict params_ranges,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    double sl_ratio, double tp_ratio, double fee,
    int min_trades, int max_trades, double max_mdd, int ema_period,
    int atr_period, double start_balance
);

// Generic Grid Search Wrapper (JSON strategy-based)
py::list optimize_generic_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::list ind_names, py::list ind_values,
    py::list filt_names, py::list filt_values,
    std::string strategy_json,
    int min_trades, int max_trades, double max_mdd, double start_balance,
    double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult
);

// [NEW] PSO Wrapper (per Architecture Report - Metaheuristic Optimization)
py::list optimize_pso_wrapper(
    py::array_t<double> open, py::array_t<double> high, py::array_t<double> low, py::array_t<double> close,
    py::list param_names, py::list param_mins, py::list param_maxs,
    py::list param_defaults_py,
    std::string strategy_json,
    int min_trades, int max_trades, double max_mdd, double start_balance,
    double fee, double tp_ratio, double sl_ratio,
    int kernel_lookback, double kernel_weight, int kernel_lookback_mult,
    int swarm_size, int max_iterations
);
