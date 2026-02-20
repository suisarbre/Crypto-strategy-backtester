# Software Requirements Specification (SRS)
## Modular Algorithmic Trading Platform

### 1. Introduction
#### 1.1 Purpose
This document specifies the software requirements for the Modular Algorithmic Trading Platform. It emphasizes the separation of concerns between the Core Execution Engine and the pluggable Strategy Modules.

#### 1.2 Scope
The software serves as a host for various trading strategies. It provides a standardized environment for data ingestion, signal evaluation, and trade execution, ensuring that different strategies can be run, tested, and optimized using a common infrastructure.

### 2. Overall Description
#### 2.1 Product Functions
*   **Core Engine:** Handles connectivity, data normalization, and global state management.
*   **Strategy Loader:** Dynamically loads strategy definitions (JSON/Python) from a repository.
*   **Signal Processor:** An abstraction layer that computes indicators and evaluates logic based on the *current* strategy's rules.
*   **Execution Layer:** Translates abstract signals (Buy/Sell) into concrete orders (Paper/Live).
*   **Optimization Module:** A generic parameter tuner that inspects the loaded strategy to define the search space.

#### 2.2 User Characteristics
*   Users range from "Strategy Consumers" (running existing JSON files) to "Strategy Creators" (writing new Python/C++ logic).

#### 2.3 Operating Environment
*   **OS:** Cross-platform (Windows, Linux, macOS).
*   **Runtime:** Python 3.10+ with optional C++ extensions for high-performance modules.

### 3. Functional Requirements

#### 3.1 Core Execution Engine (`core/trader.py`)
*   **REQ-CORE-01:** The engine shall maintain a global heartbeat tick (default 1s) independent of the strategy logic.
*   **REQ-CORE-02:** The engine shall support "Strategy Hot-Swapping," allowing the user to change the active strategy class/JSON without restarting the application.
*   **REQ-CORE-03:** The engine shall provide a standardized `DataFrame` containing OHLCV data to the active strategy.

#### 3.2 Pluggable Strategy System (`strategies/`)
*   **REQ-STRAT-01:** The system shall define a generic `BaseStrategy` interface that all strategies must implement (or align with via JSON adapter).
*   **REQ-STRAT-02:** Strategies must be definable via JSON configuration (`strategies/*.json`) for rapid prototyping and sharing.
*   **REQ-STRAT-03:** The system shall support a dynamic library of indicators (RSI, WaveTrend, etc.) that strategies can reference by name.
*   **REQ-STRAT-04:** The system shall support "Advanced Modules" (like the C++ KNN extension) as optional dependencies for strategies that require them.

#### 3.3 Universal Risk Management
*   **REQ-RM-01:** The system shall enforce global risk limits (e.g., Daily Loss Limit) that supersede individual strategy logic.
*   **REQ-RM-02:** The system shall provide standard risk tools (Trailing Stop, Breakeven) that strategies can *opt-in* to use via configuration.

#### 3.4 User Interface (`gui/dashboard.py`)
*   **REQ-UI-01:** The dashboard shall dynamically render the name and version of the *currently active* strategy.
*   **REQ-UI-02:** The dashboard shall allow users to select from a list of available strategies in the `strategies/repository`.
*   **REQ-UI-03:** Visual markers (Buy/Sell/Exit) must be generic, displaying the "Reason" tag provided by the active strategy.

#### 3.5 Generic Optimization (`core/optimizer.py`)
*   **REQ-OP-01:** The optimizer shall dynamically inspect the active strategy's JSON/Config to determine available parameters and their valid ranges.
*   **REQ-OP-02:** The optimizer shall support multi-objective fitness functions (Profit, Sharpe, Drawdown) applicable to any strategy.

### 4. Non-Functional Requirements

#### 4.1 Extensibility
*   **NFR-EXT-01:** Adding a new indicator type should not require modifying the core trading loop.
*   **NFR-EXT-02:** New strategies should be deployable by adding a file to the strategy folder, without code recompilation (for JSON strategies).

#### 4.2 Performance
*   **NFR-PERF-01:** The strategy evaluation step must complete within `<500ms` to ensure timely execution in live markets.
*   **NFR-PERF-02:** High-compute strategies (like those using AI/ML) should utilize compiled extensions (C++/Rust) where possible.

#### 4.3 Isolation
*   **NFR-ISO-01:** A failure/exception in a strategy's calculation logic must be caught by the Core Engine and should not crash the entire application (Safety Net).

### 5. Interface Requirements
*   **Strategy API:** A defined input/output schema for strategy modules (Inputs: `OHLCV DataFrame`, `Config`; Outputs: `Signal`, `Meta-data`).
*   **Control API:** Standardized hooks for starting, stopping, and reconfiguring the engine.
