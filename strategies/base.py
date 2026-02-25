
# strategies/base.py
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Defines the contract for:
    1. Analyzing data (Indicators)
    2. Generating signals (Entry/Exit)
    3. Processing signals (Execution/Risk)
    4. Exposing optimizable parameters
    """
    
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def calculate_indicators(self, df):
        """
        Calculates technical indicators and adds them to the DataFrame.
        Returns: df (pd.DataFrame)
        """
        pass

    @abstractmethod
    def generate_signals(self, df):
        """
        Generates 'final_signal' (1, -1, 0) based on logic.
        Returns: df (pd.DataFrame)
        """
        pass

    @abstractmethod
    def get_parameter_ranges(self):
        """
        Returns a dictionary of optimizable parameters and their ranges.
        Example: {'rsi_length': [14, 21], 'stop_loss': [0.01, 0.02]}
        """
        pass

    @abstractmethod
    def process_signal(self, state, price, signal, atr=0.0, extras=None):
        """
        Process the signal to execute trades and return logs.
        
        Args:
            state (TradeStateManager): Instance of state manager
            price (float): Current price
            signal (int): 1 (Long), -1 (Short), 0 (Neutral)
            atr (float): Current ATR
            extras (dict, optional): Additional signal metadata
            
        Returns:
            list[str]: List of execution logs
        """
        pass

    def get_pnl(self, state, price):
        """Common PnL calculation helper."""
        if state.position == 0: return 0.0
        
        leverage = state.entry_leverage
        
        if state.position == 1:
            raw_pnl = (price - state.avg_entry) / state.avg_entry
        else:
            raw_pnl = (state.avg_entry - price) / state.avg_entry
            
        return raw_pnl * leverage
