#include "factory.h"
#include <iostream>
#include <algorithm>
#include <cctype>

// Helper: convert string to lowercase for case-insensitive matching
static std::string to_lower(const std::string& s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), ::tolower);
    return out;
}

// Helper: resolve param with fallback aliases
static double get_param(const std::map<std::string, double>& params, 
                        const std::string& primary, const std::string& alias = "", double def = 0.0) {
    if (params.count(primary)) return params.at(primary);
    if (!alias.empty() && params.count(alias)) return params.at(alias);
    return def;
}

std::vector<double> IndicatorFactory::compute(
    const std::string& type,
    const std::string& source,
    const std::map<std::string, double>& params,
    const MarketData& data
) {
    // Helper to get source data
    std::vector<double> src_vec = data.get_source(source);
    
    // Normalize type to lowercase for case-insensitive matching
    std::string t = to_lower(type);
    
    // Map alternate type names to canonical forms
    if (t == "wavetrend_diff" || t == "wavetrend") t = "wt";
    if (t == "choppiness") t = "chop";

    if (t == "rsi") {
        int len = (int)get_param(params, "length", "", 14);
        return indicators::rsi(src_vec, len);
    }
    else if (t == "wt") {
        int ch_len = (int)get_param(params, "channel_length", "ch_len", 10);
        int avg_len = (int)get_param(params, "average_length", "avg_len", 11);
        return indicators::wavetrend(src_vec, ch_len, avg_len);
    }
    else if (t == "cci") {
        int len = (int)get_param(params, "length", "", 20);
        return indicators::cci(data.high, data.low, data.close, len);
    }
    else if (t == "adx") {
        int len = (int)get_param(params, "length", "", 20);
        return indicators::adx(data.high, data.low, data.close, len);
    }
    else if (t == "ema") {
        int len = (int)get_param(params, "length", "", 200);
        return indicators::ema(src_vec, len);
    }
    else if (t == "atr") {
        int len = (int)get_param(params, "length", "", 14);
        return indicators::atr(data.high, data.low, data.close, len);
    }
    else if (t == "chop") {
        int len = (int)get_param(params, "length", "", 14);
        return indicators::choppiness(data.high, data.low, data.close, len);
    }
    else if (t == "kernel" || t == "kernel_ls") {
         double w = get_param(params, "weight", "r", 8.0);
         int lb = (int)get_param(params, "lookback", "h", 8);
         int mult = (int)get_param(params, "mult", "", 3);
         // Return direction signal (1=rising, -1=falling, 0=flat)
         return indicators::kernel_direction(src_vec, w, lb, mult);
    }
    
    std::cerr << "[Factory] Unknown indicator type: " << type << std::endl;
    return {};
}
