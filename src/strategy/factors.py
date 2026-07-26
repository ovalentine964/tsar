"""
TSAR Factor Library — Pure Factor Computations.

23 quantitative trading factors organized by category.
Every function is pure: takes a DataFrame with OHLCV columns,
returns a pd.Series aligned to the input index.

Categories:
  - momentum (8): RSI, MACD, Stochastic, Williams %R, ROC, Momentum, CCI, MFI
  - mean_reversion (4): BB %B, Z-Score, VWAP distance, Keltner position
  - volatility (4): ATR norm, BB bandwidth, Historical Vol, ATR ratio
  - volume (4): OBV slope, Volume ROC, A/D line, Chaikin MF
  - trend (4): ADX, Aroon, Ichimoku, Supertrend
  - pattern (3): Engulfing, Pin bar, Inside bar

All functions accept **kwargs for parameter overrides.
Default parameters are sensible industry-standard values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    """True Range calculation."""
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


# ═══════════════════════════════════════════════════════════════════════
# MOMENTUM FACTORS (8)
# ═══════════════════════════════════════════════════════════════════════


def rsi(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Relative Strength Index.

    Measures momentum as ratio of average gains to average losses.
    Returns values in [0, 100]. Oversold < 30, overbought > 70.
    """
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    **kwargs: object,
) -> pd.Series:
    """MACD histogram (MACD line − signal line).

    Positive histogram = bullish momentum, negative = bearish.
    Returns the histogram series (the most trade-relevant component).
    """
    fast_ema = _ema(df["close"], fast)
    slow_ema = _ema(df["close"], slow)
    macd_line = fast_ema - slow_ema
    signal_line = _ema(macd_line, signal)
    return macd_line - signal_line


def stochastic_k(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Stochastic %K.

    Current close position relative to the high-low range over `period`.
    Returns values in [0, 100].
    """
    low_min = df["low"].rolling(window=period).min()
    high_max = df["high"].rolling(window=period).max()
    denom = high_max - low_min
    return ((df["close"] - low_min) / denom.replace(0, np.nan)) * 100.0


def stochastic_d(df: pd.DataFrame, period: int = 14, smooth: int = 3, **kwargs: object) -> pd.Series:
    """Stochastic %D (SMA of %K). Signal line for stochastic oscillator."""
    k = stochastic_k(df, period=period)
    return _sma(k, smooth)


def williams_r(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Williams %R.

    Like inverted Stochastic. Returns values in [-100, 0].
    Oversold < -80, overbought > -20.
    """
    high_max = df["high"].rolling(window=period).max()
    low_min = df["low"].rolling(window=period).min()
    denom = high_max - low_min
    return ((high_max - df["close"]) / denom.replace(0, np.nan)) * -100.0


def roc(df: pd.DataFrame, period: int = 10, **kwargs: object) -> pd.Series:
    """Rate of Change.

    Percentage change over `period` bars. Positive = price rising.
    """
    return df["close"].pct_change(periods=period) * 100.0


def momentum(df: pd.DataFrame, period: int = 10, **kwargs: object) -> pd.Series:
    """Raw momentum (price difference over `period` bars).

    Simple price change: close - close[n periods ago].
    """
    return df["close"].diff(periods=period)


def cci(df: pd.DataFrame, period: int = 20, **kwargs: object) -> pd.Series:
    """Commodity Channel Index.

    Measures price deviation from statistical mean. 
    Typical range: [-100, +100]. Extreme readings > ±200.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    sma_tp = _sma(tp, period)
    mean_dev = tp.rolling(window=period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


def mfi(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Money Flow Index.

    Volume-weighted RSI. Combines price and volume for momentum.
    Returns values in [0, 100]. Oversold < 20, overbought > 80.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    raw_mf = tp * df["volume"]
    delta = tp.diff()
    pos_mf = raw_mf.where(delta > 0, 0.0)
    neg_mf = raw_mf.where(delta < 0, 0.0)
    pos_sum = pos_mf.rolling(window=period).sum()
    neg_sum = neg_mf.rolling(window=period).sum()
    mr = pos_sum / neg_sum.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + mr))


# ═══════════════════════════════════════════════════════════════════════
# MEAN REVERSION FACTORS (4)
# ═══════════════════════════════════════════════════════════════════════


def bb_pct_b(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    **kwargs: object,
) -> pd.Series:
    """Bollinger Band %B.

    Shows where price sits within the bands. 
    0 = at lower band, 1 = at upper band, < 0 = below lower, > 1 = above upper.
    """
    sma = _sma(df["close"], period)
    std = df["close"].rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    band_width = upper - lower
    return (df["close"] - lower) / band_width.replace(0, np.nan)


def zscore(df: pd.DataFrame, period: int = 20, **kwargs: object) -> pd.Series:
    """Z-Score.

    Standard deviations from the rolling mean. 
    |Z| > 2 is statistically extreme.
    """
    mean = _sma(df["close"], period)
    std = df["close"].rolling(window=period).std()
    return (df["close"] - mean) / std.replace(0, np.nan)


def vwap_distance(df: pd.DataFrame, **kwargs: object) -> pd.Series:
    """Distance from VWAP (Volume Weighted Average Price).

    Returns percentage deviation from VWAP. Positive = above VWAP.
    VWAP is computed cumulatively over the entire window.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (tp * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return ((df["close"] - vwap) / vwap.replace(0, np.nan)) * 100.0


def keltner_position(
    df: pd.DataFrame,
    ema_period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 2.0,
    **kwargs: object,
) -> pd.Series:
    """Keltner Channel position.

    Where price sits within Keltner Channels (EMA ± ATR mult).
    Returns 0 at lower band, 1 at upper band, similar to %B.
    """
    mid = _ema(df["close"], ema_period)
    tr = _true_range(df)
    atr = tr.ewm(span=atr_period, adjust=False).mean()
    upper = mid + atr_mult * atr
    lower = mid - atr_mult * atr
    band_width = upper - lower
    return (df["close"] - lower) / band_width.replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════════════
# VOLATILITY FACTORS (4)
# ═══════════════════════════════════════════════════════════════════════


def atr_normalized(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Normalized ATR (ATR as percentage of close).

    Allows volatility comparison across different price levels.
    Returns percentage (e.g., 2.5 = 2.5% ATR relative to price).
    """
    tr = _true_range(df)
    atr = tr.ewm(span=period, adjust=False).mean()
    return (atr / df["close"].replace(0, np.nan)) * 100.0


def bb_bandwidth(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    **kwargs: object,
) -> pd.Series:
    """Bollinger Bandwidth.

    (Upper - Lower) / Middle. Measures volatility as band width.
    Low values indicate consolidation (squeeze), high values indicate trending.
    """
    sma = _sma(df["close"], period)
    std = df["close"].rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return (upper - lower) / sma.replace(0, np.nan)


def historical_volatility(df: pd.DataFrame, period: int = 20, **kwargs: object) -> pd.Series:
    """Historical Volatility (annualized).

    Standard deviation of log returns, annualized.
    Higher values = more volatile.
    """
    log_ret = np.log(df["close"] / df["close"].shift(1))
    return log_ret.rolling(window=period).std() * np.sqrt(365.0)


def atr_ratio(
    df: pd.DataFrame,
    short_period: int = 7,
    long_period: int = 14,
    **kwargs: object,
) -> pd.Series:
    """ATR Ratio (short ATR / long ATR).

    Values > 1 mean recent volatility is expanding.
    Values < 1 mean recent volatility is contracting.
    """
    tr = _true_range(df)
    atr_short = tr.ewm(span=short_period, adjust=False).mean()
    atr_long = tr.ewm(span=long_period, adjust=False).mean()
    return atr_short / atr_long.replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════════════
# VOLUME FACTORS (4)
# ═══════════════════════════════════════════════════════════════════════


def obv_slope(df: pd.DataFrame, period: int = 20, **kwargs: object) -> pd.Series:
    """OBV (On-Balance Volume) slope.

    Linear regression slope of OBV over `period` bars, normalized.
    Positive = volume confirming uptrend, negative = distribution.
    """
    direction = np.sign(df["close"].diff())
    obv = (direction * df["volume"]).cumsum()
    # Linear regression slope via rolling covariance/variance
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _slope(y: np.ndarray) -> float:
        if len(y) < period:
            return np.nan
        y_mean = y.mean()
        return ((x - x_mean) * (y - y_mean)).sum() / x_var

    return obv.rolling(window=period).apply(_slope, raw=True)


def volume_roc(df: pd.DataFrame, period: int = 10, **kwargs: object) -> pd.Series:
    """Volume Rate of Change.

    Percentage change in volume over `period` bars.
    Spikes indicate increased interest/conviction.
    """
    return df["volume"].pct_change(periods=period) * 100.0


def accumulation_distribution(df: pd.DataFrame, **kwargs: object) -> pd.Series:
    """Accumulation/Distribution Line.

    Measures money flow based on close position within the high-low range.
    Rising A/D = accumulation (buying pressure), falling = distribution.
    """
    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    mfv = mfm * df["volume"]
    return mfv.cumsum()


def chaikin_money_flow(df: pd.DataFrame, period: int = 20, **kwargs: object) -> pd.Series:
    """Chaikin Money Flow.

    Volume-weighted measure of accumulation/distribution over `period`.
    Positive = buying pressure, negative = selling pressure. Range: [-1, 1].
    """
    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    mfv = mfm * df["volume"]
    return mfv.rolling(window=period).sum() / df["volume"].rolling(window=period).sum().replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════════════
# TREND FACTORS (4)
# ═══════════════════════════════════════════════════════════════════════


def adx(df: pd.DataFrame, period: int = 14, **kwargs: object) -> pd.Series:
    """Average Directional Index.

    Measures trend strength regardless of direction.
    ADX > 25 = trending, ADX < 20 = ranging. Range: [0, 100].
    """
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = _true_range(df)
    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100.0 * (_ema(plus_dm, period) / atr.replace(0, np.nan))
    minus_di = 100.0 * (_ema(minus_dm, period) / atr.replace(0, np.nan))

    di_sum = plus_di + minus_di
    dx = ((plus_di - minus_di).abs() / di_sum.replace(0, np.nan)) * 100.0
    return _ema(dx, period)


def aroon_oscillator(df: pd.DataFrame, period: int = 25, **kwargs: object) -> pd.Series:
    """Aroon Oscillator.

    Aroon Up − Aroon Down. Range: [-100, 100].
    Positive = uptrend, negative = downtrend. Near 0 = no trend.
    """
    high = df["high"]
    low = df["low"]
    period_int = int(period)

    def _aroon_up(window: np.ndarray) -> float:
        idx = np.argmax(window)
        return ((period_int - idx) / period_int) * 100.0

    def _aroon_down(window: np.ndarray) -> float:
        idx = np.argmin(window)
        return ((period_int - idx) / period_int) * 100.0

    a_up = high.rolling(window=period_int).apply(_aroon_up, raw=True)
    a_down = low.rolling(window=period_int).apply(_aroon_down, raw=True)
    return a_up - a_down


def ichimoku(
    df: pd.DataFrame,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    **kwargs: object,
) -> pd.Series:
    """Ichimoku cloud signal.

    Returns a composite score in [-1, 1]:
      +1 = all bullish (price above cloud, tenkan > kijun, etc.)
      -1 = all bearish
      0  = neutral / mixed signals.
    """
    high, low, close = df["high"], df["low"], df["close"]

    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2.0
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2.0
    senkou_a = ((tenkan_sen + kijun_sen) / 2.0).shift(kijun)
    senkou_b_line = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2.0).shift(kijun)

    score = pd.Series(0.0, index=df.index)
    # Price above cloud
    cloud_top = pd.concat([senkou_a, senkou_b_line], axis=1).max(axis=1)
    cloud_bot = pd.concat([senkou_a, senkou_b_line], axis=1).min(axis=1)
    score = score.where(~(close > cloud_top), score + 0.33)
    score = score.where(~(close < cloud_bot), score - 0.33)
    # Tenkan/Kijun cross
    score = score.where(~(tenkan_sen > kijun_sen), score + 0.33)
    score = score.where(~(tenkan_sen < kijun_sen), score - 0.33)
    # Cloud direction
    score = score.where(~(senkou_a > senkou_b_line), score + 0.34)
    score = score.where(~(senkou_a < senkou_b_line), score - 0.34)
    return score.clip(-1.0, 1.0)


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
    **kwargs: object,
) -> pd.Series:
    """Supertrend direction.

    Returns +1 for uptrend (bullish), -1 for downtrend (bearish).
    Based on ATR bands around HL2.
    """
    tr = _true_range(df)
    atr = tr.ewm(span=period, adjust=False).mean()
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    direction = pd.Series(1, index=df.index, dtype=float)
    final_upper = upper_band.copy()
    final_lower = lower_band.copy()

    for i in range(1, len(df)):
        # Lower band: ratchet up
        if lower_band.iloc[i] > final_lower.iloc[i - 1] or df["close"].iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = lower_band.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        # Upper band: ratchet down
        if upper_band.iloc[i] < final_upper.iloc[i - 1] or df["close"].iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = upper_band.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        # Direction flip
        if direction.iloc[i - 1] == 1:
            if df["close"].iloc[i] < final_lower.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = 1
        else:
            if df["close"].iloc[i] > final_upper.iloc[i]:
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1

    return direction


# ═══════════════════════════════════════════════════════════════════════
# PATTERN FACTORS (3)
# ═══════════════════════════════════════════════════════════════════════


def engulfing(df: pd.DataFrame, **kwargs: object) -> pd.Series:
    """Engulfing pattern detection.

    Returns +1 for bullish engulfing, -1 for bearish engulfing, 0 for none.
    Bullish: prev candle bearish, current candle bullish, current body engulfs prev body.
    Bearish: prev candle bullish, current candle bearish, current body engulfs prev body.
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)

    prev_bearish = prev_c < prev_o
    curr_bullish = c > o
    bullish_body = (c > prev_o) & (o < prev_c)
    bullish_engulf = prev_bearish & curr_bullish & bullish_body

    prev_bullish = prev_c > prev_o
    curr_bearish = c < o
    bearish_body = (o > prev_c) & (c < prev_o)
    bearish_engulf = prev_bullish & curr_bearish & bearish_body

    result = pd.Series(0.0, index=df.index)
    result = result.where(~bullish_engulf, 1.0)
    result = result.where(~bearish_engulf, -1.0)
    return result


def pin_bar(df: pd.DataFrame, wick_ratio: float = 2.0, **kwargs: object) -> pd.Series:
    """Pin bar (hammer/shooting star) detection.

    Returns +1 for bullish pin bar (long lower wick), -1 for bearish (long upper wick).
    Wick must be `wick_ratio` times the body size.
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    total_range = h - l
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

    # Bullish pin bar: long lower wick
    bullish_pin = (lower_wick > wick_ratio * body) & (lower_wick > upper_wick) & (total_range > 0)
    # Bearish pin bar: long upper wick
    bearish_pin = (upper_wick > wick_ratio * body) & (upper_wick > lower_wick) & (total_range > 0)

    result = pd.Series(0.0, index=df.index)
    result = result.where(~bullish_pin, 1.0)
    result = result.where(~bearish_pin, -1.0)
    return result


def inside_bar(df: pd.DataFrame, **kwargs: object) -> pd.Series:
    """Inside bar detection.

    Returns 1 when current bar is entirely within previous bar's range.
    Indicates consolidation / indecision before potential breakout.
    """
    curr_inside = (df["high"] <= df["high"].shift(1)) & (df["low"] >= df["low"].shift(1))
    return curr_inside.astype(float)


# ═══════════════════════════════════════════════════════════════════════
# FACTOR REGISTRY (for FactorLibrary to import)
# ═══════════════════════════════════════════════════════════════════════

FACTOR_REGISTRY: dict[str, dict[str, object]] = {
    # Momentum
    "rsi": {
        "func": rsi,
        "category": "momentum",
        "description": "Relative Strength Index (momentum oscillator)",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    "macd": {
        "func": macd,
        "category": "momentum",
        "description": "MACD histogram (trend-following momentum)",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
        "universe": ["crypto", "equity", "forex"],
    },
    "stochastic_k": {
        "func": stochastic_k,
        "category": "momentum",
        "description": "Stochastic %K oscillator",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    "stochastic_d": {
        "func": stochastic_d,
        "category": "momentum",
        "description": "Stochastic %D (signal line)",
        "default_params": {"period": 14, "smooth": 3},
        "universe": ["crypto", "equity", "forex"],
    },
    "williams_r": {
        "func": williams_r,
        "category": "momentum",
        "description": "Williams %R oscillator",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    "roc": {
        "func": roc,
        "category": "momentum",
        "description": "Rate of Change (percentage momentum)",
        "default_params": {"period": 10},
        "universe": ["crypto", "equity", "forex"],
    },
    "momentum": {
        "func": momentum,
        "category": "momentum",
        "description": "Raw price momentum (price diff)",
        "default_params": {"period": 10},
        "universe": ["crypto", "equity", "forex"],
    },
    "cci": {
        "func": cci,
        "category": "momentum",
        "description": "Commodity Channel Index",
        "default_params": {"period": 20},
        "universe": ["crypto", "equity", "forex", "commodity"],
    },
    "mfi": {
        "func": mfi,
        "category": "momentum",
        "description": "Money Flow Index (volume-weighted RSI)",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity"],
    },
    # Mean Reversion
    "bb_pct_b": {
        "func": bb_pct_b,
        "category": "mean_reversion",
        "description": "Bollinger Band %B position",
        "default_params": {"period": 20, "std_dev": 2.0},
        "universe": ["crypto", "equity", "forex"],
    },
    "zscore": {
        "func": zscore,
        "category": "mean_reversion",
        "description": "Z-Score (standard deviations from mean)",
        "default_params": {"period": 20},
        "universe": ["crypto", "equity", "forex"],
    },
    "vwap_distance": {
        "func": vwap_distance,
        "category": "mean_reversion",
        "description": "Distance from VWAP (percentage)",
        "default_params": {},
        "universe": ["crypto", "equity"],
    },
    "keltner_position": {
        "func": keltner_position,
        "category": "mean_reversion",
        "description": "Keltner Channel position",
        "default_params": {"ema_period": 20, "atr_period": 14, "atr_mult": 2.0},
        "universe": ["crypto", "equity", "forex"],
    },
    # Volatility
    "atr_normalized": {
        "func": atr_normalized,
        "category": "volatility",
        "description": "Normalized ATR (% of price)",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    "bb_bandwidth": {
        "func": bb_bandwidth,
        "category": "volatility",
        "description": "Bollinger Bandwidth (volatility squeeze indicator)",
        "default_params": {"period": 20, "std_dev": 2.0},
        "universe": ["crypto", "equity", "forex"],
    },
    "historical_volatility": {
        "func": historical_volatility,
        "category": "volatility",
        "description": "Annualized historical volatility",
        "default_params": {"period": 20},
        "universe": ["crypto", "equity"],
    },
    "atr_ratio": {
        "func": atr_ratio,
        "category": "volatility",
        "description": "ATR ratio (short/long, volatility expansion/contraction)",
        "default_params": {"short_period": 7, "long_period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    # Volume
    "obv_slope": {
        "func": obv_slope,
        "category": "volume",
        "description": "OBV linear regression slope",
        "default_params": {"period": 20},
        "universe": ["crypto", "equity"],
    },
    "volume_roc": {
        "func": volume_roc,
        "category": "volume",
        "description": "Volume Rate of Change",
        "default_params": {"period": 10},
        "universe": ["crypto", "equity"],
    },
    "accumulation_distribution": {
        "func": accumulation_distribution,
        "category": "volume",
        "description": "Accumulation/Distribution Line",
        "default_params": {},
        "universe": ["crypto", "equity"],
    },
    "chaikin_money_flow": {
        "func": chaikin_money_flow,
        "category": "volume",
        "description": "Chaikin Money Flow",
        "default_params": {"period": 20},
        "universe": ["crypto", "equity"],
    },
    # Trend
    "adx": {
        "func": adx,
        "category": "trend",
        "description": "Average Directional Index (trend strength)",
        "default_params": {"period": 14},
        "universe": ["crypto", "equity", "forex"],
    },
    "aroon_oscillator": {
        "func": aroon_oscillator,
        "category": "trend",
        "description": "Aroon Oscillator (trend direction)",
        "default_params": {"period": 25},
        "universe": ["crypto", "equity", "forex"],
    },
    "ichimoku": {
        "func": ichimoku,
        "category": "trend",
        "description": "Ichimoku cloud composite signal",
        "default_params": {"tenkan": 9, "kijun": 26, "senkou_b": 52},
        "universe": ["crypto", "equity"],
    },
    "supertrend": {
        "func": supertrend,
        "category": "trend",
        "description": "Supertrend direction indicator",
        "default_params": {"period": 10, "multiplier": 3.0},
        "universe": ["crypto", "equity", "forex"],
    },
    # Pattern
    "engulfing": {
        "func": engulfing,
        "category": "pattern",
        "description": "Engulfing candlestick pattern",
        "default_params": {},
        "universe": ["crypto", "equity", "forex"],
    },
    "pin_bar": {
        "func": pin_bar,
        "category": "pattern",
        "description": "Pin bar / hammer / shooting star pattern",
        "default_params": {"wick_ratio": 2.0},
        "universe": ["crypto", "equity", "forex"],
    },
    "inside_bar": {
        "func": inside_bar,
        "category": "pattern",
        "description": "Inside bar (consolidation) pattern",
        "default_params": {},
        "universe": ["crypto", "equity", "forex"],
    },
}
