#include "indicators.h"
#include <numeric>
#include <iostream>

namespace indicators {

    std::vector<double> ema(const std::vector<double>& src, int period) {
        std::vector<double> out(src.size(), 0.0);
        if (src.empty()) return out;
        
        double alpha = 2.0 / (period + 1);
        
        // Initialize with SMA for the first 'period' elements? 
        // Or simple recursive start. Let's match Pandas ewm(adjust=False) usually used in typical python libs,
        // OR ta library behavior. 'ta' library usually starts strictly.
        // For performance/simplicity, we start with first value.
        
        out[0] = src[0];
        for (size_t i = 1; i < src.size(); ++i) {
            out[i] = (src[i] - out[i-1]) * alpha + out[i-1];
        }
        return out;
    }

    std::vector<double> rsi(const std::vector<double>& src, int period) {
        std::vector<double> out(src.size(), 50.0); // Default neutral
        if (src.size() < (size_t)period + 1) return out;

        std::vector<double> gains(src.size(), 0.0);
        std::vector<double> losses(src.size(), 0.0);

        for (size_t i = 1; i < src.size(); ++i) {
            double change = src[i] - src[i-1];
            if (change > 0) gains[i] = change;
            else losses[i] = -change;
        }

        // Smoothed averages (Wilder's Smoothing)
        double avg_gain = 0.0;
        double avg_loss = 0.0;

        // First average (SMA)
        for (int i = 1; i <= period; ++i) {
            avg_gain += gains[i];
            avg_loss += losses[i];
        }
        avg_gain /= period;
        avg_loss /= period;

        for (size_t i = period + 1; i < src.size(); ++i) {
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period;
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period;

            if (avg_loss == 0) {
                out[i] = 100.0;
            } else {
                double rs = avg_gain / avg_loss;
                out[i] = 100.0 - (100.0 / (1.0 + rs));
            }
        }
        return out;
    }

    std::vector<double> wavetrend(const std::vector<double>& src, int ch_len, int avg_len) {
        // ESA = EMA(src, ch_len)
        auto esa = ema(src, ch_len);
        
        // D = EMA(Abs(src - ESA), ch_len)
        std::vector<double> abs_diff(src.size());
        for(size_t i=0; i<src.size(); ++i) abs_diff[i] = std::abs(src[i] - esa[i]);
        auto d = ema(abs_diff, ch_len);
        
        // CI = (src - ESA) / (0.015 * D)
        std::vector<double> ci(src.size(), 0.0);
        for(size_t i=0; i<src.size(); ++i) {
            if(d[i] != 0) ci[i] = (src[i] - esa[i]) / (0.015 * d[i]);
        }
        
        // WT1 = EMA(CI, avg_len)
        return ema(ci, avg_len);
    }

    std::vector<double> cci(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period) {
        size_t n = close.size();
        std::vector<double> out(n, 0.0);
        if (n < (size_t)period) return out;
        
        std::vector<double> tp(n);
        for(size_t i=0; i<n; ++i) tp[i] = (high[i] + low[i] + close[i]) / 3.0;
        
        // Simple Moving Average of TP
        // And Mean Deviation
        for(size_t i = period-1; i < n; ++i) {
            double sum_tp = 0.0;
            for(int j=0; j<period; ++j) sum_tp += tp[i-j];
            double sma_tp = sum_tp / period;
            
            double sum_dev = 0.0;
            for(int j=0; j<period; ++j) sum_dev += std::abs(tp[i-j] - sma_tp);
            double mean_dev = sum_dev / period;
            
            if(mean_dev != 0) out[i] = (tp[i] - sma_tp) / (0.015 * mean_dev);
        }
        
        return out;
    }

    std::vector<double> adx(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period) {
        // Simplified ADX implementation
        size_t n = close.size();
        std::vector<double> out(n, 0.0);
        if(n < (size_t)period) return out;
        
        std::vector<double> tr(n, 0.0);
        std::vector<double> dm_plus(n, 0.0);
        std::vector<double> dm_minus(n, 0.0);
        
        for(size_t i=1; i<n; ++i) {
            double hl = high[i] - low[i];
            double hc = std::abs(high[i] - close[i-1]);
            double lc = std::abs(low[i] - close[i-1]);
            tr[i] = std::max({hl, hc, lc});
            
            double up = high[i] - high[i-1];
            double down = low[i-1] - low[i];
            
            if(up > down && up > 0) dm_plus[i] = up;
            if(down > up && down > 0) dm_minus[i] = down;
        }
        
        // Smoothed
        // First value is sum? Or SMA? Wilder used sum for first, then smooth.
        // We closely follow standard EMA smoothing: alpha = 1/period
        
        auto smooth = [&](const std::vector<double>& in) {
            std::vector<double> s(n, 0.0);
            double sum = 0.0;
            for(int i=1; i<=period; ++i) sum += in[i]; // sum of period
            s[period] = sum; // Initial
            
            for(size_t i=period+1; i<n; ++i) {
                s[i] = s[i-1] - (s[i-1]/period) + in[i];
            }
            return s;
        };
        
        auto sm_tr = smooth(tr);
        auto sm_p = smooth(dm_plus);
        auto sm_m = smooth(dm_minus);
        
        std::vector<double> dx(n, 0.0);
        for(size_t i=period; i<n; ++i) {
            double sum_dm = sm_p[i] + sm_m[i];
            if(sum_dm != 0) {
                dx[i] = (std::abs(sm_p[i] - sm_m[i]) / sum_dm) * 100.0;
            }
        }
        
        // ADX is usually SMA(DX, period) or Wilder smoothed? Often EMA or SMA.
        // Ta-lib uses SMA(DX) usually? Or Wilder?
        // Let's use EMA for DX smoothing as it's common.
        double alpha = 2.0 / (period + 1);
        out[period*2] = dx[period*2]; // Approx start
        for(size_t i=period*2 + 1; i<n; ++i) {
             out[i] = (dx[i] - out[i-1]) * alpha + out[i-1];
        }
        
        return out;
    }

    std::vector<double> rq_kernel(const std::vector<double>& src, double relative_weight, int lookback, int lookback_mult) {
        size_t n = src.size();
        std::vector<double> y_hat(n);
        
        // Initialize with source
        for(size_t i=0; i<n; ++i) y_hat[i] = src[i];
        
        for (size_t i = 0; i < n; ++i) {
            double current_weight = 0.0;
            double cumulative_weight = 0.0;
            
            // Standardized lookback range: lookback * multiplier
            long start_j = (long)i - (long)(lookback * lookback_mult); 
            if (start_j < 0) start_j = 0;
            
            for (size_t j = (size_t)start_j; j <= i; j++) {
                double diff = (double)i - (double)j;
                double w = std::pow(
                    1.0 + (std::pow(diff, 2) / (2.0 * std::pow(relative_weight, 2))), 
                    -relative_weight
                );
                current_weight += src[j] * w;
                cumulative_weight += w;
            }
            
            if (cumulative_weight != 0) {
                y_hat[i] = current_weight / cumulative_weight;
            }
        }
        return y_hat;
    }

    std::vector<double> atr(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period) {
        size_t n = close.size();
        std::vector<double> out(n, 0.0);
        if(n < (size_t)period) return out;
        
        std::vector<double> tr(n, 0.0);
        
        // TR Calculation
        for(size_t i=1; i<n; ++i) {
            double hl = high[i] - low[i];
            double hc = std::abs(high[i] - close[i-1]);
            double lc = std::abs(low[i] - close[i-1]);
            tr[i] = std::max({hl, hc, lc});
        }
        
        // Smoothed ATR (RMA/Wilder's)
        // First value is usually SMA of TR
        double sum_tr = 0.0;
        for(int i=1; i<=period; ++i) sum_tr += tr[i];
        out[period] = sum_tr / period;
        
        for(size_t i=period+1; i<n; ++i) {
            out[i] = (out[i-1] * (period - 1) + tr[i]) / period;
        }
        
        return out;
    }

    std::vector<double> choppiness(const std::vector<double>& high, const std::vector<double>& low, const std::vector<double>& close, int period) {
        size_t n = close.size();
        std::vector<double> out(n, 50.0); // Default neutral
        if(n < (size_t)period) return out;
        
        std::vector<double> tr(n, 0.0);
        // TR Calculation
        for(size_t i=1; i<n; ++i) {
            double hl = high[i] - low[i];
            double hc = std::abs(high[i] - close[i-1]);
            double lc = std::abs(low[i] - close[i-1]);
            tr[i] = std::max({hl, hc, lc});
        }
        
        // Sum of TR
        // Rolling max High / min Low
        for(size_t i=period; i<n; ++i) {
            double sum_tr = 0.0;
            double max_h = high[i];
            double min_l = low[i];
            
            for(int j=0; j<period; ++j) {
                sum_tr += tr[i-j];
                if(high[i-j] > max_h) max_h = high[i-j];
                if(low[i-j] < min_l) min_l = low[i-j];
            }
            
            double range = max_h - min_l;
            if(range == 0) range = 0.00001; // Avoid div by zero
            
            // Formula: 100 * Log10(SumTR / Range) / Log10(Period)
            double ratio = sum_tr / range;
            if(ratio <= 0) ratio = 1.0; 
            
            out[i] = 100.0 * std::log10(ratio) / std::log10((double)period);
        }
        return out;
    }

}
