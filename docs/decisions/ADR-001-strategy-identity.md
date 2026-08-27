# ADR-001: Strategy identity keys on filename stem

Date: 2026-08-26
Status: Implemented

## Context

`gui/dashboard.py::_discover_strategies()` keyed the strategy dropdown on the
JSON's lowercased `strategy_name` ("Regime Rider" → `'regime rider'`), while
`strategies.STRATEGY_MAP` keyed on short identifiers (`standard`, `aggressive`,
`lorentzian`). Two of the four shipped strategies — `regime_rider.json` and
`simple.json` (display name `Robust_Trend_Guard`) — matched neither map and were
unreachable from the UI.

The two lookup sites also disagreed on what to do about a miss:

- `get_strategy()` used `.get(name, STRATEGY_MAP['default'])` and silently fell
  back to `LorentzianStrategy`, which ignores JSON rules entirely.
- `TradeStateManager.update_config()` used a bare `.get()` and no-op'd, leaving
  the previously loaded strategy running.

Either way the bot traded under a different strategy than the one selected, with
no error. `docs/GAP_ANALYSIS.md` recorded hot-swap as **Implemented** (REQ-UI-02).

## Decision

Strategy identity is the **filename stem**: `repository/regime_rider.json` →
`regime_rider`. The `strategy_name` field inside the JSON is display text only
and is never used as a lookup key.

Discovery lives in exactly one place, `strategies.discover_strategies()`, which
the dashboard now calls instead of reimplementing.

`STRATEGY_MAP` holds only Python-implemented strategies. Any discovered JSON
resolves to `JsonStrategyLogic` automatically, so adding a strategy file never
requires editing a map.

`resolve_strategy_class()` raises `UnknownStrategyError` on a miss. No fallbacks.

## Consequences

- `simple.json` is selected as `simple` but displays as "Robust_Trend_Guard".
  The dropdown shows labels while its value stays the canonical key.
- Renaming a strategy file is now a breaking change for any saved config that
  references the old stem.
- An unknown strategy key now raises where it previously traded on silently.
  This is deliberate: a loud failure at startup beats a quiet wrong-strategy run.
- `get_strategy()` now also loads the named strategy's own JSON into
  `config['strategy_json']`. Previously it always loaded `strategies.json`
  regardless of which strategy was requested.

## Verification

`tests/test_strategy_resolution.py::TestStrategyDiscovery` pins that every
shipped JSON resolves, that keys are stems rather than display names, and that
an unknown key raises.
