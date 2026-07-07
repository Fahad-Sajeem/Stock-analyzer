"""Technical indicators — pure functions over pandas Series (PLAN 7.1).

Hand-rolled (no TA-Lib) for portability and testability. Wilder-smoothed
indicators (RSI, ATR, ADX) use an exponential moving average with alpha = 1/n,
which is the standard RMA definition used by TradingView / pandas-ta.

Convention: every series is indexed by date, ordered oldest -> newest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    # adjust=False, no min_periods: classic recursive EMA seeded at the first price.
    return series.ewm(span=n, adjust=False).mean()


def rma(series: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing (running moving average), alpha = 1/n."""
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def slope(series: pd.Series, n: int) -> pd.Series:
    """Simple n-bar slope: (value - value n bars ago) / n."""
    return (series - series.shift(n)) / n


def roc(series: pd.Series, n: int) -> pd.Series:
    """Rate of change in percent over n bars."""
    return (series / series.shift(n) - 1.0) * 100.0


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # avg_loss == 0 (only gains) -> RSI 100; avg_gain == 0 (only losses) -> RSI 0.
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(avg_gain != 0.0, 0.0)
    return out


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return rma(true_range(high, low, close), n)


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (ADX, +DI, -DI)."""
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr_n = rma(true_range(high, low, close), n)
    plus_di = 100.0 * rma(plus_dm, n) / tr_n
    minus_di = 100.0 * rma(minus_dm, n) / tr_n
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_series = rma(dx, n)
    return adx_series, plus_di, minus_di


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(
    close: pd.Series, n: int = 20, k: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return (mid, upper, lower, width) where width = (upper-lower)/mid."""
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    width = (upper - lower) / mid
    return mid, upper, lower, width


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Percentile rank (0-100) of the latest value within its trailing window.

    Vectorized with a sliding-window view (C-level) — a naive rolling ``.apply``
    is ~1000x slower at full-universe scale and blows the Phase 3 runtime budget.
    NaNs inside a window are excluded from both numerator and denominator.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    arr = series.to_numpy(dtype="float64")
    n = len(arr)
    out = np.full(n, np.nan)
    min_p = max(2, window // 4)
    if n < min_p:
        return pd.Series(out, index=series.index)

    # Bulk: full trailing windows via a strided view (no copy).
    if n >= window:
        w = sliding_window_view(arr, window)          # (n-window+1, window)
        last = w[:, -1][:, None]
        valid = ~np.isnan(w)
        le = np.sum((w <= last) & valid, axis=1)
        cnt = np.sum(valid, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            pct = np.where(cnt > 0, le / cnt * 100.0, np.nan)
        pct = np.where(np.isnan(w[:, -1]), np.nan, pct)  # NaN current value -> NaN
        out[window - 1 :] = pct

    # Head: expanding windows for the first (min_p-1 .. window-2) positions.
    for i in range(min_p - 1, min(window - 1, n)):
        head = arr[: i + 1]
        cur = head[-1]
        if np.isnan(cur):
            continue
        valid = ~np.isnan(head)
        cnt = valid.sum()
        if cnt > 0:
            out[i] = np.sum((head <= cur) & valid) / cnt * 100.0
    return pd.Series(out, index=series.index)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).fillna(0.0).cumsum()


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, mult: float = 3.0
) -> pd.Series:
    """Supertrend line (used as a trailing-stop reference). Returns the line;
    when price is above it the trend is up, below it the trend is down."""
    atr_n = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    basic_upper = (hl2 + mult * atr_n).to_numpy()
    basic_lower = (hl2 - mult * atr_n).to_numpy()

    n = len(close)
    c = close.to_numpy()
    fu = np.full(n, np.nan)  # final upper band
    fl = np.full(n, np.nan)  # final lower band
    st_arr = np.full(n, np.nan)

    # Seed at the first bar where ATR is defined.
    start = int(np.argmax(~np.isnan(basic_upper))) if (~np.isnan(basic_upper)).any() else n
    if start < n:
        fu[start] = basic_upper[start]
        fl[start] = basic_lower[start]
        st_arr[start] = fu[start]  # start assuming downtrend; flips immediately if price above

    for i in range(start + 1, n):
        # Final upper band: tighten unless price broke above it last bar.
        fu[i] = (
            basic_upper[i]
            if (basic_upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1])
            else fu[i - 1]
        )
        # Final lower band: tighten unless price broke below it last bar.
        fl[i] = (
            basic_lower[i]
            if (basic_lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1])
            else fl[i - 1]
        )
        if st_arr[i - 1] == fu[i - 1]:
            st_arr[i] = fl[i] if c[i] > fu[i] else fu[i]
        else:  # was tracking the lower band (uptrend)
            st_arr[i] = fu[i] if c[i] < fl[i] else fl[i]

    return pd.Series(st_arr, index=close.index)
