
import pandas as pd
import numpy as np
import json
import os

class SignalEvaluator:
    def __init__(self, strategy_json):
        if isinstance(strategy_json, str):
            self.config = json.loads(strategy_json)
        else:
            self.config = strategy_json
        
        self.entry_rules = self.config.get("entry_rules", {})
        
    def evaluate(self, df, params):
        """
        Evaluate entry signals for the entire DataFrame vectorially.
        :param df: DataFrame with columns matching indicator names
        :param params: Dictionary of strategy parameters
        :return: DataFrame with 'final_signal' column (1, -1, 0)
        """
        n = len(df)
        long_mask = pd.Series(True, index=df.index)
        short_mask = pd.Series(True, index=df.index)
        
        # Evaluate Long Rules
        if "long" in self.entry_rules:
            long_mask = self._evaluate_group(self.entry_rules["long"], df, params)
            
        # Evaluate Short Rules
        if "short" in self.entry_rules:
            short_mask = self._evaluate_group(self.entry_rules["short"], df, params)
            
        # Combine
        # 1 if Long, -1 if Short. If both, depends on priority. usually Long first or mutually exclusive.
        # If both are true, it's ambiguous. In C++, checked Long then Short.
        # But usually they are mutually exclusive (KNN 1 vs -1).
        
        signals = np.zeros(n, dtype=int)
        signals[long_mask] = 1
        signals[short_mask] = -1 
        # Note: if both True, -1 overwrites 1. C++ logic:
        # if long_ok return 1; if short_ok return -1.
        # So Long has priority in C++.
        # Let's match C++:
        # signals = np.where(long_mask, 1, np.where(short_mask, -1, 0))
        
        # To strictly match C++ sequence:
        final_sig = np.zeros(n, dtype=int)
        
        # We need numpy arrays for speed/indexing
        lm = long_mask.values if hasattr(long_mask, 'values') else long_mask
        sm = short_mask.values if hasattr(short_mask, 'values') else short_mask
        
        final_sig = np.where(lm, 1, np.where(sm, -1, 0))
        
        return final_sig

    def evaluate_exit(self, df, params):
        """
        Evaluate exit signals. 
        Returns Series with bitmask: 1=Long Exit, 2=Short Exit.
        """
        n = len(df)
        exit_mask = pd.Series(0, index=df.index, dtype=int)
        
        rules = self.config.get("exit_rules", {})
        
        # Check Long Exit Rules
        if "long" in rules and rules["long"]:
            mask = self._evaluate_group(rules["long"], df, params)
            exit_mask |= (mask.astype(int) * 1)
        
        # Check Short Exit Rules
        if "short" in rules and rules["short"]:
            mask = self._evaluate_group(rules["short"], df, params)
            exit_mask |= (mask.astype(int) * 2)
                
        return exit_mask.values

    def _evaluate_group(self, rules_list, df, params):
        """
        Evaluate a list of rules (implicit AND).
        """
        overall_mask = pd.Series(True, index=df.index)
        
        for rule in rules_list:
            mask = self._evaluate_rule(rule, df, params)
            overall_mask = overall_mask & mask
            
        return overall_mask

    def _evaluate_rule(self, rule, df, params):
        r_type = rule.get("type")
        
        if r_type == "knn_signal":
            # Matches 'pred_signal' column or similar
            # In C++, we passed preds[t]. In Python, df['pred_signal']
            val = rule.get("value")
            if "pred_signal" not in df.columns:
                return pd.Series(False, index=df.index)
            return df["pred_signal"] == val
            
        elif r_type == "condition":
            # if param is true, evaluate 'then' rules.
            # logic: (!cond) OR (cond AND sub_rules)
            cond_param = rule.get("if")
            toggle = params.get(cond_param, 0.0) > 0.5
            
            if not toggle:
                return pd.Series(True, index=df.index)
            
            # If toggle is True, ALL sub-rules must pass (implicit AND)
            sub_rules = rule.get("then", [])
            return self._evaluate_group(sub_rules, df, params)
            
        elif r_type == "compare":
            left_key = rule.get("left")
            op = rule.get("op")
            right_val = rule.get("right")
            
            # Resolve Left
            if left_key in df.columns:
                left = df[left_key]
            elif left_key in params:
                 left = params[left_key]
            else:
                 # Warning? Assume constants?
                 left = float(left_key) if str(left_key).replace('.','').isdigit() else 0.0
            
            # Resolve Right
            if isinstance(right_val, str) and right_val in params:
                right = params[right_val]
            elif isinstance(right_val, str) and right_val in df.columns:
                right = df[right_val]
            else:
                try:
                    right = float(right_val)
                except (ValueError, TypeError):
                    # Unknown param name not in params or df — use 0.0 as safe default
                    right = 0.0
                
            if op == "<": return left < right
            if op == ">": return left > right
            if op == "<=": return left <= right
            if op == ">=": return left >= right
            if op == "==": return left == right
            if op == "!=": return left != right
            
            # [NEW] Crossover Support
            if op in ["cross_over", "cross_under"]:
                # Helper to get previous value
                def get_prev(val):
                    if hasattr(val, 'shift'): return val.shift(1)
                    return val # Constant
                
                prev_left = get_prev(left)
                prev_right = get_prev(right)
                
                if op == "cross_over":
                    # (PrevL <= PrevR) AND (CurrL > CurrR)
                    # Note: FillNA with False to avoid false signals at start
                    return ((prev_left <= prev_right) & (left > right)).fillna(False)
                    
                if op == "cross_under":
                    # (PrevL >= PrevR) AND (CurrL < CurrR)
                    return ((prev_left >= prev_right) & (left < right)).fillna(False)
            
        elif rule.get("op") == "and" and "rules" in rule: # [Fixed] Check rules key directly
             return self._evaluate_group(rule.get("rules", []), df, params)

        return pd.Series(True, index=df.index)
