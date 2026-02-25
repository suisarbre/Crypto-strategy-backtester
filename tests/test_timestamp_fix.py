"""Test Binance timestamp sync fix."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data.data_loader import exchange

offset = exchange.options.get('timeDifference', 0)
print(f'Time offset from server: {offset}ms')

t = exchange.fetch_ticker('BTC/USDT')
print(f'BTC/USDT price: ${t["last"]:,.2f}')
print('Timestamp sync OK')
