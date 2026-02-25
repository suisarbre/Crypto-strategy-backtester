#include <pybind11/stl.h>
#include "knn.h"
#include "backtester.h"
#include "optimizer.h"

namespace py = pybind11;

PYBIND11_MODULE(cpp_engine, m) {
    m.doc() = "Optimized financial trading engine powered by C++ (Modularized)";

    py::class_<FastKNN>(m, "FastKNN")
        .def(py::init<int>())
        .def("fit", &FastKNN::fit)
        .def("predict", &FastKNN::predict);

    m.def("fast_backtest", &fast_backtest_wrapper, "A function to backtest trading strategy quickly",
        py::arg("prices"), py::arg("signals"), py::arg("exit_signals"), // [NEW]
        py::arg("atr"),
        py::arg("leverage"), py::arg("start_balance"), 
        py::arg("sl_ratio"), py::arg("sl_multiplier"),
        py::arg("tp_ratio"), py::arg("fee"));
    
    m.def("optimize_grid_search", &optimize_grid_search_wrapper, "A function to run grid search optimization in C++",
        py::arg("open"), py::arg("high"), py::arg("low"), py::arg("close"),
        py::arg("params_ranges"),
        py::arg("kernel_lookback"), py::arg("kernel_weight"), py::arg("kernel_lookback_mult"),
        py::arg("sl_ratio"), py::arg("tp_ratio"), py::arg("fee"),
        py::arg("min_trades"), py::arg("max_trades"), py::arg("max_mdd"), py::arg("ema_period"),
        py::arg("atr_period"), py::arg("start_balance"));

    // [New] Generic Recursive Grid Search
    m.def("optimize_generic", &optimize_generic_wrapper, "Generic Recursive Grid Search",
        py::arg("open"), py::arg("high"), py::arg("low"), py::arg("close"),
        py::arg("ind_names"), py::arg("ind_values"),
        py::arg("filt_names"), py::arg("filt_values"),
        py::arg("strategy_json"),
        py::arg("min_trades"), py::arg("max_trades"), py::arg("max_mdd"), py::arg("start_balance"),
        py::arg("fee"), py::arg("tp_ratio"), py::arg("sl_ratio"),
        py::arg("kernel_lookback"), py::arg("kernel_weight"), py::arg("kernel_lookback_mult"));

    // [New] PSO Optimizer (per Architecture Report - Metaheuristic Optimization)
    m.def("optimize_pso", &optimize_pso_wrapper, "Particle Swarm Optimization",
        py::arg("open"), py::arg("high"), py::arg("low"), py::arg("close"),
        py::arg("param_names"), py::arg("param_mins"), py::arg("param_maxs"),
        py::arg("param_defaults"),
        py::arg("strategy_json"),
        py::arg("min_trades"), py::arg("max_trades"), py::arg("max_mdd"), py::arg("start_balance"),
        py::arg("fee"), py::arg("tp_ratio"), py::arg("sl_ratio"),
        py::arg("kernel_lookback"), py::arg("kernel_weight"), py::arg("kernel_lookback_mult"),
        py::arg("swarm_size"), py::arg("max_iterations"));
}
