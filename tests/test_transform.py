"""Quick test to verify transformation function works"""
ranges = {
    "rsi": [12, 14, 16],
    "wt_ch": [8, 10, 12],
    "wt_avg": [19, 21, 23],
    "cci": [17, 20, 23],
    "adx": [12, 14, 16],
    "k": [8, 12, 16],
    "adx_threshold": [20.0, 25.0, 30.0],
    "chop_threshold": [40.0, 50.0, 60.0],
    "lev": [1, 2, 3],
    "sl_multiplier": [3.0, 5.0, 7.0],
    "ema_period": [80.0, 140.0, 200.0],
    "use_ema_filter": [0.0, 1.0],
    "use_adx_filter": [0.0, 1.0]
}

from core.optimizer import transform_ranges_to_generic_format

ind_names, ind_values, filt_names, filt_values = transform_ranges_to_generic_format(ranges)

print("Indicators:")
for name, values in zip(ind_names, ind_values):
    print(f"  {name}: {values}")

print("\nFilters:")
for name, values in zip(filt_names, filt_values):
    print(f"  {name}: {values}")
