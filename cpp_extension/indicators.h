#pragma once
#include <vector>
#include <cmath>
#include <algorithm>

namespace indicators {

    std::vector<double> rsi(const std::vector<double>& src, int period);
    
    // WaveTrend components
    struct WaveTrendResult {
        std::vector<double> wt1;
        std::vector<double> wt2; // Optional, usually wt1 is enough for signals
    };
    std::vector<double> wavetrend(const std::vector<double>& src, int ch_len, int avg_len);
    
    std::vector<double> cci(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period);
    
    std::vector<double> adx(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period);
    
    std::vector<double> ema(const std::vector<double>& src, int period);

    // Kernel Regression (Rational Quadratic)
    std::vector<double> rq_kernel(const std::vector<double>& src, double relative_weight, int lookback, int lookback_mult);

    // ATR
    std::vector<double> atr(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period);

    // Choppiness Index
    std::vector<double> choppiness(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period);

}
