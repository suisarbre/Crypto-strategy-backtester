#include "signal_evaluator.h"
#include <iostream>

using json = nlohmann::json;

// Constructor implementation moved below


// Helper to parse individual rule object
Rule parse_rule_obj(const json& j) {
    Rule r;
    r.type = j.value("type", "");
    
    if (r.type == "compare") {
        r.left_ind = j.value("left", "");
        r.op = j.value("op", "");
        
        auto right = j["right"];
        if (right.is_number()) {
            r.is_right_param = false;
            r.right_const = right.get<double>();
        } else {
            r.is_right_param = true;
            r.right_val = right.get<std::string>();
        }
    } else if (r.type == "condition") {
        r.left_ind = j.value("if", ""); // The toggle param
        // Sub rules
        if (j.contains("then")) {
            for (const auto& item : j["then"]) {
                r.sub_rules.push_back(parse_rule_obj(item));
            }
        }
    } else if (r.type == "knn_signal") {
        r.is_right_param = false;
        r.right_const = j.value("value", 0);
    }
    
    return r;
}

void SignalEvaluator::parse_rules(const json& j_list, std::vector<Rule>& rules) {
    for (const auto& item : j_list) {
         // Handle top-level "op": "and" wrapper if present, or just list.
         // In my JSON: "long": [ {"op": "and", "rules": [...]} ]
         if (item.value("op", "") == "and" && item.contains("rules")) {
             for (const auto& r_json : item["rules"]) {
                 rules.push_back(parse_rule_obj(r_json));
             }
         } else {
             rules.push_back(parse_rule_obj(item));
         }
    }
}

// Re-impl constructor with correct parsing
SignalEvaluator::SignalEvaluator(const std::string& json_content) {
    auto j = json::parse(json_content);
    config.name = j.value("strategy_name", "Unknown");
    
    if (j.contains("entry_rules")) {
        if (j["entry_rules"].contains("long")) {
            parse_rules(j["entry_rules"]["long"], config.long_entry_rules);
        }
        if (j["entry_rules"].contains("short")) {
            parse_rules(j["entry_rules"]["short"], config.short_entry_rules);
        }
    }
    
    // [FIX] Parse exit rules
    if (j.contains("exit_rules")) {
        if (j["exit_rules"].contains("long")) {
            parse_rules(j["exit_rules"]["long"], long_exit_rules);
        }
        if (j["exit_rules"].contains("short")) {
            parse_rules(j["exit_rules"]["short"], short_exit_rules);
        }
    }
}

bool SignalEvaluator::check_rule(const Rule& r, size_t idx, 
    const std::map<std::string, const std::vector<double>*>& inds, 
    const std::map<std::string, double>& params, 
    int knn_sig) 
{
    if (r.type == "knn_signal") {
        return knn_sig == (int)r.right_const;
    }
    
    if (r.type == "condition") {
        // Toggle check
        // "if": "use_adx_filter" -> param must be > 0.5
        double toggle_val = 0.0;
        if (params.count(r.left_ind)) toggle_val = params.at(r.left_ind);
        
        if (toggle_val > 0.5) {
            // Check all sub-rules
            for (const auto& sub : r.sub_rules) {
                if (!check_rule(sub, idx, inds, params, knn_sig)) return false;
            }
        }
        return true; 
    }
    
    if (r.type == "compare") {
        double left_val = 0.0;
        
        // Resolve Left (Indicator or Param?) - Match Python logic!
        // Python checks: df.columns first, then params
        if (inds.count(r.left_ind)) {
             left_val = (*inds.at(r.left_ind))[idx];
        } else if (params.count(r.left_ind)) {
             // [FIX] Fallback to params if not in indicators (same as Python)
             left_val = params.at(r.left_ind);
        } else {
            // Missing both - this is an error
            // But to match Python's lenient behavior, try parsing as number
            try {
                left_val = std::stod(r.left_ind);
            } catch (...) {
                return false; // Truly missing
            }
        }
        
        
        double right_val = 0.0;
        if (r.is_right_param) {
            // Right side is a param/indicator name
            // [FIX] Check indicators first, then params (match Python)
            if (inds.count(r.right_val)) {
                right_val = (*inds.at(r.right_val))[idx];
            } else if (params.count(r.right_val)) {
                right_val = params.at(r.right_val);
            } else {
                return false; // Missing indicator/param
            }
        } else {
            right_val = r.right_const;
        }
        
        if (r.op == "<") return left_val < right_val;
        if (r.op == ">") return left_val > right_val;
        if (r.op == "<=") return left_val <= right_val;
        if (r.op == ">=") return left_val >= right_val;
        if (r.op == "==") return std::abs(left_val - right_val) < 1e-9;
    }
    
    return true;
}

int SignalEvaluator::evaluate(
    size_t index, 
    const std::map<std::string, const std::vector<double>*>& indicators,
    const std::map<std::string, double>& params,
    int knn_signal
) {
    // Check Long
    bool long_ok = true;
    for (const auto& r : config.long_entry_rules) {
        if (!check_rule(r, index, indicators, params, knn_signal)) {
            long_ok = false;
            break;
        }
    }
    if (long_ok) return 1;
    
    // Check Short
    bool short_ok = true;
    for (const auto& r : config.short_entry_rules) {
        if (!check_rule(r, index, indicators, params, knn_signal)) {
            short_ok = false;
            break;
        }
    }
    if (short_ok) return -1;
    
    return 0;
}

// [NEW] Evaluate Exit Logic (Stateless)
// Returns bitmask: 1=Long Exit, 2=Short Exit
int SignalEvaluator::evaluate_exit(
    size_t index,
    const std::map<std::string, const std::vector<double>*>& indicators,
    const std::map<std::string, double>& params
) {
    int exit_mask = 0;
    
    // Check Long Exit Rules
    if (!long_exit_rules.empty()) {
        bool long_exit_met = true;
        for (const auto& r : long_exit_rules) {
            if (!check_rule(r, index, indicators, params, 0)) {
                long_exit_met = false;
                break;
            }
        }
        if (long_exit_met) exit_mask |= 1;
    }

    // Check Short Exit Rules
    if (!short_exit_rules.empty()) {
        bool short_exit_met = true;
        for (const auto& r : short_exit_rules) {
            if (!check_rule(r, index, indicators, params, 0)) {
                short_exit_met = false;
                break;
            }
        }
        if (short_exit_met) exit_mask |= 2;
    }
    
    return exit_mask;
}
