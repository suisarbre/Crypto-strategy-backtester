# Comprehensive Gap Analysis Report

> ### ✅ CLOSED — historical snapshot, do not treat as an open to-do list
>
> **Written 2026-02-20. Re-verified 2026-08-26: every gap below has been closed,
> and closed exactly as this report's own recommendations specified.**
>
> | Gap as reported | State on 2026-08-26 |
> |---|---|
> | Daily Loss Limit — 🔴 Missing, "zero execution logic" | **Implemented.** `TradeStateManager._check_daily_loss()` sets `is_paused` on breach (Priority 1 as written). |
> | Universal Trailing Stop — 🟡 Partial | **Implemented.** Centralized in `_check_risk_management()` behind `USE_TRAILING_STOP` / `TS_ACTIVATION` / `TS_CALLBACK` (Priority 2). |
> | Breakeven Logic — 🟡 Partial | **Implemented.** Same method, behind `USE_BREAKEVEN` / `BE_TRIGGER` / `BE_OFFSET` (Priority 2). |
> | Priority 3 — risk unit tests | **Done.** `tests/test_risk_management.py`. |
>
> One correction to the record: REQ-UI-02 (Strategy Hot-Swap) was marked
> **Implemented** here, but was in fact broken in two ways until 2026-08-26 —
> the swap never reached signal generation, and two of four strategies were
> unreachable by name. See `docs/decisions/ADR-001-strategy-identity.md`.
>
> Retained as a dated record. New findings belong in a new report or an ADR.

**Date:** 2026-02-20
**Scope:** C++ Engine, Python Core, Strategies, Dashboard
**Status:** **Mixed** (C++ & Dashboard: Resolved, Core Logic: Gaps Found)

## 1. Executive Summary

This report compares the current codebase against the **Software Requirements Specification (SRS v1.0)**.
*   **C++ Extension**: Fully Generalized and Documented. (Previously a major gap, now resolved).
*   **Dashboard**: Functionally complete and well-documented. Matches UI requirements.
*   **Core Logic**: **Major Gaps** identified in Universal Risk Management. The "Global Risk Enforcement" described in the SRS is partially missing or loosely implemented.

## 2. Component Analysis

### 2.1 C++ Execution Engine (Generic Optimization)
| Requirement | SRS ID | Implementation Status | Notes |
| :--- | :--- | :--- | :--- |
| **Dynamic Indicators** | REQ-STRAT-03 | **Fully Implemented** | `IndicatorFactory` enables dynamic computation from JSON. |
| **Generic Optimization** | REQ-OP-01 | **Fully Implemented** | `Optimizer` generic loop is fully functional and tested. |
| **Documentation** | N/A | **Resolved** | All diagrams updated to reflect the Generic architecture. |

### 2.2 Dashboard (User Interface)
| Requirement | SRS ID | Implementation Status | Notes |
| :--- | :--- | :--- | :--- |
| **Active Strategy Info** | REQ-UI-01 | **Implemented** | Displays Name & Version on load/swap. |
| **Strategy Hot-Swap** | REQ-UI-02 | **Implemented** | Dropdown allows immediate swapping of logic & config. |
| **Generic Markers** | REQ-UI-03 | **Implemented** | Markers support generic "Reason" tags and dynamic PnL colors. |
| **Performance** | N/A | **Optimized** | Uses background loops and partial updates to prevent UI freezing. |

### 2.3 Core Logic & Risk Management (Python)
| Requirement | SRS ID | Implementation Status | Notes |
| :--- | :--- | :--- | :--- |
| **Global Heartbeat** | REQ-CORE-01 | **Implemented** | `TradeStateManager` + Dashboard Background Loop. |
| **Standard DataFrame** | REQ-CORE-03 | **Implemented** | `fetch_raw_data` provides normalized OHLCV. |
| **Daily Loss Limit** | **REQ-RM-01** | 🔴 **Missing** | `TradeStateManager` tracks MDD but has **zero execution logic** to stop trading if a daily loss limit is hit. |
| **Universal Trailing Stop** | **REQ-RM-02** | 🟡 **Partial** | `trailing_stop_price` field exists in State, but the update logic is delegated to individual Strategies. SRS implies it should be a core feature strategies can just "toggle on". |
| **Breakeven Logic** | **REQ-RM-02** | 🟡 **Partial** | Code contains comments `# [Breakeven Check] - Breakeven is moved to Signal Logic?`. Not implemented in State Manager. |

### 2.4 Strategy Interface
| Requirement | SRS ID | Implementation Status | Notes |
| :--- | :--- | :--- | :--- |
| **Base Interface** | REQ-STRAT-01 | **Implemented** | `BaseStrategy` enforces contract. |
| **JSON Configuration** | REQ-STRAT-02 | **Implemented** | `strategies.json` is fully supported and hot-swappable. |

## 3. Recommendations

### Priority 1: Implement Global Risk Management
The **SRS REQ-RM-01** is a critical safety feature.
1.  **Add `daily_loss_limit`** to `config.py` and `TradeStateManager`.
2.  **Implement Logic**: In `TradeStateManager.process_tick`, check if `(start_balance_of_day - current_balance) / start_balance_of_day > limit`.
3.  **Action**: If limit hit, set `self.is_paused = True` and log a warning.

### Priority 2: Centralize Trailing Stop & Breakeven
To meet **REQ-RM-02**, move common logic out of individual strategies:
1.  **Move Logic**: Implement `check_trailing_stop(price)` and `check_breakeven(price)` inside `TradeStateManager.process_tick`.
2.  **Configuration**: Strategies should just set flags in the config (e.g., `use_trailing_stop: true`, `ts_activation: 0.02`), and the Core Engine handles the rest.

### Priority 3: Unit Tests for Risk Module
Since Risk Management is a safety-critical feature, it requires dedicated unit tests (Simulation of 50% drop, Trailing Stop activation, etc.).
