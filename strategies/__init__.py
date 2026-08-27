import glob
import json
import os
import config as cfg
from .json_strategy import JsonStrategyLogic
from .lorentzian import LorentzianStrategy

_HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_DIR = os.path.join(_HERE, 'repository')
DEFAULT_STRATEGY_PATH = os.path.join(_HERE, 'strategies.json')

# Python-implemented strategies only. JSON-backed strategies are discovered from
# the repository and resolve to JsonStrategyLogic automatically — adding a new
# .json file must never require an edit here (ADR-001).
STRATEGY_MAP = {
    'lorentzian': LorentzianStrategy,
}


class UnknownStrategyError(KeyError):
    """Raised when a strategy key matches neither a Python strategy nor a JSON file."""


def discover_strategies():
    """
    Map strategy key -> JSON path.

    Keys are filename stems: repository/regime_rider.json -> 'regime_rider'.
    The 'strategy_name' field inside the JSON is display text only and is never
    used as a lookup key (ADR-001) — it used to be, which left two of the four
    shipped strategies unreachable.
    """
    found = {}
    if os.path.isdir(REPOSITORY_DIR):
        for path in sorted(glob.glob(os.path.join(REPOSITORY_DIR, '*.json'))):
            key = os.path.splitext(os.path.basename(path))[0].lower()
            found[key] = path

    # strategies.json is the fallback 'standard' when the repository lacks one.
    if 'standard' not in found and os.path.exists(DEFAULT_STRATEGY_PATH):
        found['standard'] = DEFAULT_STRATEGY_PATH

    return found


def strategy_path(name):
    """JSON path for a strategy key, or None for Python-implemented strategies."""
    return discover_strategies().get(str(name).lower())


def display_name(name):
    """Human-readable label for a strategy key (the JSON's 'strategy_name')."""
    path = strategy_path(name)
    if not path:
        return str(name)
    try:
        with open(path, 'r') as f:
            return json.load(f).get('strategy_name', name)
    except Exception:
        return str(name)


def resolve_strategy_class(name):
    """
    Class backing a strategy key.

    Raises UnknownStrategyError rather than falling back — a silent fallback
    previously ran trades under a different strategy than the one selected.
    """
    key = str(name).lower()

    if key in STRATEGY_MAP:
        return STRATEGY_MAP[key]
    if key in discover_strategies():
        return JsonStrategyLogic

    known = sorted(set(STRATEGY_MAP) | set(discover_strategies()))
    raise UnknownStrategyError(
        f"Unknown strategy '{name}'. Known strategies: {', '.join(known)}"
    )


def build_strategy_config(name, base=None):
    """
    Config dict for a strategy: system config, then the strategy's own JSON.

    Also stashes the raw JSON under 'strategy_json' so JsonStrategyLogic can
    evaluate its rules without the dashboard having to inject it separately.
    """
    config = {k: v for k, v in cfg.__dict__.items() if not k.startswith('__')}
    if base:
        config.update(base)

    path = strategy_path(name)
    if path:
        try:
            with open(path, 'r') as f:
                raw = f.read()
            config.update(json.loads(raw))
            config['strategy_json'] = raw
        except Exception as e:
            print(f"[Warning] Failed to load strategy JSON for '{name}': {e}")

    config['active_strategy'] = str(name).lower()
    return config


def get_strategy(name, base_config=None):
    """Instantiate the strategy registered under `name`."""
    logic_cls = resolve_strategy_class(name)
    return logic_cls(build_strategy_config(name, base_config))
