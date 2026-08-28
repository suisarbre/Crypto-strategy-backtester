import csv
import os
import json
from datetime import datetime

class CsvLogger:
    def __init__(self, filename, fieldnames):
        self.filename = filename
        self.fieldnames = fieldnames
        self._init_file()

    def _init_file(self):
        parent = os.path.dirname(self.filename)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(self.filename):
            with open(self.filename, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()

    def log(self, data):
        """Append a row to the CSV log file."""
        # Auto-add timestamp
        if 'Timestamp' not in data:
            data['Timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
        with open(self.filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(data)


class TradeLogger(CsvLogger):
    def __init__(self, filename='logs/trades.csv'):
        super().__init__(filename, [
            'Timestamp', 'Event', 'Symbol', 'Side', 'Price', 'Qty', 
            'Realized_PnL', 'Balance', 'Entry_Leverage', 'Config_Dump'
        ])
        
    def log_trade(self, event, symbol, side, price, pnl, balance, leverage, config=None):
        config_dump = json.dumps(config) if config else ''
        self.log({
            'Event': event,
            'Symbol': symbol,
            'Side': side,
            'Price': price,
            'Qty': 1,  # Fixed for now (spot/futures qty logic TBD)
            'Realized_PnL': f"{pnl:.4f}",
            'Balance': f"{balance:.2f}",
            'Entry_Leverage': leverage,
            'Config_Dump': config_dump
        })

class OptimizationLogger(CsvLogger):
    def __init__(self, filename='logs/optimizations.csv'):
        super().__init__(filename, [
            'Timestamp', 'Best_Score', 'Predicted_Balance', 'Win_Rate', 'MDD', 
            'Best_Leverage', 'Selected_Strategy', 'Best_Params'
        ])

    def log_optimization(self, score, balance, win_rate, mdd, params):
        self.log({
            'Best_Score': f"{score:.4f}",
            'Predicted_Balance': f"{balance:.2f}",
            'Win_Rate': f"{win_rate:.2f}",
            'MDD': f"{mdd:.2f}",
            'Best_Leverage': params.get('leverage', 1),
            'Selected_Strategy': params.get('active_strategy', 'unknown'),
            'Best_Params': json.dumps(params)
        })
