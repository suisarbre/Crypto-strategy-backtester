# C++ Engine Generalization Plan

## Goal
Transform the `cpp_engine` from a specialized "Lorentzian Optimizer" into a **Generic Strategy Optimizer** that can process *any* strategy defined in `strategies.json`, without recompiling C++ code.

## Core Problem
Currently, `optimizer.cpp` hardcodes the feature engineering step:
```cpp
// Current Hardcoded Logic
auto rsi_vec = indicators::rsi(src, rsi_len);
auto wt_vec = indicators::wavetrend(src, wt1, wt2);
auto adx_vec = indicators::adx(h, l, c, adx_len);
// ... feed to KNN ...
```

## Solution Design

### 1. The `IndicatorFactory` Pattern
We need a dynamic mapping from config strings to function calls.

```cpp
// Proposed Interface
class IndicatorFactory {
public:
    static std::vector<double> compute(
        const std::string& type, 
        const std::map<std::string, double>& params,
        const MarketData& data
    );
};
```

### 2. Strategy Configuration Schema Update
The `strategies.json` must explicitly define which indicators are required for the strategy, including their input parameters.

**Current (Implicit):**
```json
{ "name": "Lorentzian" } // C++ "knows" what to do
```

**Proposed (Explicit):**
```json
{
    "name": "GenericStrategy",
    "features": [
        { "name": "my_rsi", "type": "rsi", "params": { "period": "rsi_length" }, "source": "close" },
        { "name": "my_adx", "type": "adx", "params": { "period": "adx_length" } }
    ]
}
```

### 3. Refactoring `optimizer.cpp` loop

The optimization loop will change from:
1.  Hardcoded `rsi`, `wt`, `adx` calls.
2.  Hardcoded `FastKNN` training.

To:
1.  **Feature Loop**: Iterate over `json["features"]`.
    *   Resolve parameters (dynamic optimization variable OR static constant).
    *   Call `IndicatorFactory::compute`.
    *   Store result in `std::map<string, vector<double>> feature_map`.
2.  **Model Training (Optional)**: Check if `json["model"]` exists (e.g., KNN).
    *   If yes, assemble `X_train` from specified feature names.
    *   Train model, store predictions in `feature_map["signal"]`.
3.  **Evaluation**: Pass `feature_map` to `SignalEvaluator`.

## Implementation Steps

### Step 1: Create `IndicatorFactory` (`cpp_extension/factory.cpp`)
- Implement a static dispatcher.
- Support `rsi`, `ema`, `sma`, `adx`, `atr`, `cci`, `wavetrend`, `kernel`.
- **Constraint**: Must handle generic inputs (standardize on `vector<double>` and `OHLC` struct).

### Step 2: Update `strategies.json` for Lorentzian
- We must "backport" the Lorentzian logic into this new explicit generic format.
- Define the Lorentzian features explicitly in the JSON so the generic engine produces the exact same result.

### Step 3: Refactor `optimizer.cpp`
- Delete hardcoded feature block.
- Implement the "Feature Loop" described above.
- Ensure OpenMP parallelism still works (thread-local `feature_map`).

### Step 4: Python Binding Update
- No major changes to `bindings.cpp` needed, but transparency on passing the full JSON is critical.

## verification
1.  **Regression Test**: Run `tests/test_lorentzian.py` using the NEW C++ engine. It must produce identical results to the legacy engine.
2.  **New Strategy Test**: Create a simple "RSI Strategy" in JSON (without KNN) and verify the C++ engine optimizes it correctly.
