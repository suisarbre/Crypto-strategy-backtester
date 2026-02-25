import json
import os
import config as cfg
from .json_strategy import JsonStrategyLogic
from .lorentzian import LorentzianStrategy

STRATEGY_MAP = {
    'standard': JsonStrategyLogic,
    'aggressive': JsonStrategyLogic,
    'lorentzian': LorentzianStrategy,
    'default': LorentzianStrategy
}

def get_config_from_json():
    """Load default strategy parameters from strategies.json"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(current_dir, 'strategies.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
                # Flatten or use definitions? 
                # For now, return the whole dict as config.
                # Strategies like Lorentzian expect keys at root or similar.
                # But strategies.json has 'definitions', 'entry_rules'.
                # We might need to flatten definitions->indicators parameters?
                # Actually, LorentzianStrategy does self.config.get('rsi_length').
                # strategies.json definitions use "length": "rsi_length".
                # But where are the VALUES?
                # AHH, the values are NOT in strategies.json? 
                # strategies.json defines the *structure* or *schema*.
                # The values usually come from user config or defaults.
                # LorentzianStrategy.py has defaults: get('rsi_length', 14).
                
                # So passing an empty dict is better than crashing, 
                # but passing system config is best.
                return data
    except Exception as e:
        print(f"[Warning] Failed to load strategies.json: {e}")
    return {}

def get_strategy(name):
    """
    Returns an instantiated strategy class with configuration.
    """
    # 1. Resolve Class
    logic_cls = STRATEGY_MAP.get(name.lower(), STRATEGY_MAP['default'])
    
    # 2. Build Config
    # Start with System Config (module attributes to dict)
    config = {k: v for k, v in cfg.__dict__.items() if not k.startswith('__')}
    
    # Merge with Strategy JSON (optional, but good for metadata)
    json_config = get_config_from_json()
    config.update(json_config)
    
    # 3. Instantiate with Config
    return logic_cls(config)
