#include "knn.h"
#include <cmath>
#include <algorithm>

FastKNN::FastKNN(int k_neighbors) : k(k_neighbors) {}

void FastKNN::fit(py::array_t<double> X, py::array_t<int> y) {
    py::buffer_info buf_X = X.request();
    py::buffer_info buf_y = y.request();

    double* ptr_X = static_cast<double*>(buf_X.ptr);
    int* ptr_y = static_cast<int*>(buf_y.ptr);

    size_t n_samples = buf_X.shape[0];
    size_t n_features = buf_X.shape[1];

    train_data.clear();
    train_data.reserve(n_samples);

    for (size_t i = 0; i < n_samples; ++i) {
        DataPoint dp;
        dp.features.reserve(n_features);
        for (size_t j = 0; j < n_features; ++j) {
            dp.features.push_back(ptr_X[i * n_features + j]);
        }
        dp.label = ptr_y[i];
        train_data.push_back(dp);
    }
}

py::array_t<int> FastKNN::predict(py::array_t<double> X) {
    py::buffer_info buf_X = X.request();
    double* ptr_X = static_cast<double*>(buf_X.ptr);
    
    size_t n_samples = buf_X.shape[0];
    size_t n_features = buf_X.shape[1];

    std::vector<int> predictions(n_samples);
    std::vector<std::pair<double, int>> neighbors; 
    neighbors.reserve(train_data.size());

    for (size_t i = 0; i < n_samples; ++i) {
        neighbors.clear();
        const double* current_test_ptr = &ptr_X[i * n_features];

        for (const auto& train_point : train_data) {
            double dist = 0.0;
            for (size_t f = 0; f < n_features; ++f) {
                // Lorentzian distance: log(1 + |a - b|) per feature dimension
                // Robust to outliers — compresses large differences via log
                dist += std::log(1.0 + std::abs(current_test_ptr[f] - train_point.features[f]));
            }
            neighbors.push_back({dist, train_point.label});
        }

        if (neighbors.size() > (size_t)k) {
            std::partial_sort(neighbors.begin(), neighbors.begin() + k, neighbors.end());
        }

        int vote_1 = 0;
        int vote_minus_1 = 0;

        for (int j = 0; j < k && j < (int)neighbors.size(); ++j) {
            int label = neighbors[j].second;
            if (label == 1) vote_1++;
            else if (label == -1) vote_minus_1++;
        }

        if (vote_1 > vote_minus_1) predictions[i] = 1;
        else if (vote_minus_1 > vote_1) predictions[i] = -1;
        else predictions[i] = -1; // Tie-break: prefer -1
    }

    return py::array_t<int>({static_cast<long>(n_samples)}, {sizeof(int)}, predictions.data());
}

// Internal method for C++ use
std::vector<int> FastKNN::predict_internal(const std::vector<std::vector<double>>& X) {
    size_t n_samples = X.size();
    if (n_samples == 0) return {};
    size_t n_features = X[0].size();
    
    std::vector<int> predictions(n_samples);
    std::vector<std::pair<double, int>> neighbors; 
    neighbors.reserve(train_data.size());
    
    #pragma omp parallel for
    for (int i = 0; i < (int)n_samples; ++i) {
        // Thread-local neighbors vector or re-allocate inside?
        // Allocating inside is easiest for correctness.
        std::vector<std::pair<double, int>> local_neighbors;
        local_neighbors.reserve(train_data.size());
        
        const std::vector<double>& current_feat = X[i];

        for (const auto& train_point : train_data) {
            double dist = 0.0;
            for (size_t f = 0; f < n_features && f < current_feat.size(); ++f) {
                // Lorentzian distance: log(1 + |a - b|) per feature dimension
                dist += std::log(1.0 + std::abs(current_feat[f] - train_point.features[f]));
            }
            local_neighbors.push_back({dist, train_point.label});
        }

        if (local_neighbors.size() > (size_t)k) {
            std::partial_sort(local_neighbors.begin(), local_neighbors.begin() + k, local_neighbors.end());
        }

        int vote_1 = 0;
        int vote_minus_1 = 0;

        for (int j = 0; j < k && j < (int)local_neighbors.size(); ++j) {
            int label = local_neighbors[j].second;
            if (label == 1) vote_1++;
            else if (label == -1) vote_minus_1++;
        }

        if (vote_1 > vote_minus_1) predictions[i] = 1;
        else if (vote_minus_1 > vote_1) predictions[i] = -1;
        else predictions[i] = -1;
    }
    return predictions;
}

void FastKNN::fit_internal(const std::vector<std::vector<double>>& X, const std::vector<int>& y) {
    size_t n_samples = X.size();
    if (n_samples == 0) return;
    size_t n_features = X[0].size();
    
    train_data.clear();
    train_data.reserve(n_samples);
    
    for (size_t i = 0; i < n_samples; ++i) {
        DataPoint dp;
        dp.features = X[i]; // Vector copy
        dp.label = y[i];
        train_data.push_back(dp);
    }
}
