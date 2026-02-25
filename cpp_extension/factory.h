#pragma once
#include <vector>
#include <string>
#include <map>
#include "indicators.h"

struct MarketData {
    // Data references
    std::vector<double> open;
    std::vector<double> high;
    std::vector<double> low;
    std::vector<double> close;
    
    // Derived sources (lazy or pre-calc? For simplicity, we compute on fly or store)
    // Actually, to avoid allocations, we might just compute on fly in get_source
    // But get_source returns const ref.
    // So we need to store them if we want to return ref.
    // Let's just store basic 4.
    
    std::vector<double> get_source(const std::string& source_name) const {
        if (source_name == "open") return open;
        if (source_name == "high") return high;
        if (source_name == "low") return low;
        if (source_name == "close") return close;
        
        size_t n = close.size();
        std::vector<double> res(n);
        
        if (source_name == "ohlc4") {
            for(size_t i=0; i<n; ++i) res[i] = (open[i]+high[i]+low[i]+close[i])/4.0;
            return res;
        }
        if (source_name == "hlc3") {
            for(size_t i=0; i<n; ++i) res[i] = (high[i]+low[i]+close[i])/3.0;
            return res;
        }
        if (source_name == "hl2") {
            for(size_t i=0; i<n; ++i) res[i] = (high[i]+low[i])/2.0;
            return res;
        }
        
        return close; // Fallback
    }
};

class IndicatorFactory {
public:
    static std::vector<double> compute(
        const std::string& type,
        const std::string& source,
        const std::map<std::string, double>& params,
        const MarketData& data
    );
};
