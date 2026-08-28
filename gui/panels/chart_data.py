"""
The heavy chart pipeline: OHLCV -> indicators -> signals -> candles + markers.

This was a closure (`_heavy_loader`) inside a 174-line method, which made it
untestable and put the datetime-resolution bug somewhere nobody would look. It
is a plain function now: no NiceGUI, no dashboard reference, no I/O beyond the
loader it is handed.
"""
from analysis.indicators import add_indicators
from analysis.signals import generate_signals
from core.backtester import run_backtest_with_markers, generate_signal_markers
from utils import to_epoch_seconds


def _finite(x):
    """Chart JSON can't carry NaN/Inf — Lightweight Charts rejects the payload."""
    x = float(x)
    if x != x or abs(x) == float('inf'):
        return None
    return x


def to_candles(df):
    """DataFrame -> Lightweight Charts candle dicts, with epoch-second times."""
    # Resolution-independent. pandas 2+ yields datetime64[ms] on a fresh fetch
    # and datetime64[us] via the CSV cache, so a hardcoded //10**9 is wrong by
    # 10**3-10**6 and lands every candle in 1970.
    times = to_epoch_seconds(df['timestamp']).tolist()
    opens = df['open'].tolist()
    highs = df['high'].tolist()
    lows = df['low'].tolist()
    closes = df['close'].tolist()

    return [
        {
            'time': int(t),
            'open': _finite(o), 'high': _finite(h),
            'low': _finite(l), 'close': _finite(c),
        }
        for t, o, h, l, c in zip(times, opens, highs, lows, closes)
    ]


def clean_marker(m):
    """Coerce a marker to JSON-safe primitives."""
    return {
        'time': int(m['time']),
        'position': str(m['position']),
        'color': str(m['color']),
        'shape': str(m['shape']),
        'text': str(m.get('text', '')),
    }


def build_chart_payload(df, config, strategy_json=None, warmup=50):
    """
    Run the full pipeline over `df` and return everything the chart needs.

    Pure with respect to the UI — safe to call from a worker thread.

    Returns: (df, config, candles, markers, n_signal_markers, n_trade_markers)
    """
    df = add_indicators(df, config)
    df = generate_signals(df, config, strategy_json=strategy_json)

    trade_markers = run_backtest_with_markers(df, config)
    signal_markers = generate_signal_markers(df, warmup=warmup)

    candles = to_candles(df)

    cleaned_signals = [clean_marker(m) for m in (signal_markers or [])]
    cleaned_trades = [clean_marker(m) for m in (trade_markers or [])]
    markers = sorted(cleaned_signals + cleaned_trades, key=lambda x: x['time'])

    return df, config, candles, markers, len(cleaned_signals), len(cleaned_trades)
