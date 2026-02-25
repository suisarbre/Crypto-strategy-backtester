#pragma once
#include <string>
#include <vector>
#include <map>
#include <memory>
#include "json.hpp" // Use local nlohmann/json

using json = nlohmann::json;

// Simplified Rule Structure
struct Rule {
    std::string type; // "compare", "condition"
    std::string left_ind;
    std::string op; // ">", "<", "=="
    std::string right_val; // can be number or param name
    bool is_right_param = false;
    double right_const = 0.0;
    
    // For nested conditions
    std::vector<Rule> sub_rules; 
};

struct StrategyConfig {
    std::string name;
    std::vector<Rule> long_entry_rules;
    std::vector<Rule> short_entry_rules;
};

class SignalEvaluator {
public:
    SignalEvaluator(const std::string& json_content);
    
    // Evaluate signal at specific index using provided indicator maps
    int evaluate(
        size_t index, 
        const std::map<std::string, const std::vector<double>*>& indicators,
        const std::map<std::string, double>& params,
        int knn_signal
    );

    // [NEW] Evaluate Exit Rules
    // Returns bitmask: 1=Long Exit, 2=Short Exit
    int evaluate_exit(
        size_t index,
        const std::map<std::string, const std::vector<double>*>& indicators,
        const std::map<std::string, double>& params
    );

private:
    StrategyConfig config;
    void parse_rules(const json& j, std::vector<Rule>& rules);
    bool check_rule(const Rule& r, size_t idx, const std::map<std::string, const std::vector<double>*>& inds, const std::map<std::string, double>& params, int knn_sig);
    
    // [NEW] Exit Rules Storage
    std::vector<Rule> long_exit_rules;
    std::vector<Rule> short_exit_rules;
};
