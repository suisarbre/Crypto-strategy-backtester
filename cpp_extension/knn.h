#pragma once
#include <vector>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

namespace py = pybind11;

struct DataPoint {
    std::vector<double> features;
    int label;
};

class FastKNN {
private:
    std::vector<DataPoint> train_data;
    int k;

public:
    FastKNN(int k_neighbors);
    void fit(py::array_t<double> X, py::array_t<int> y);
    py::array_t<int> predict(py::array_t<double> X);
    
    // Internal method for C++ usage
    std::vector<int> predict_internal(const std::vector<std::vector<double>>& X);
    void fit_internal(const std::vector<std::vector<double>>& X, const std::vector<int>& y);
};
