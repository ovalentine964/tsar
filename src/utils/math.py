"""
Math utilities — Common mathematical functions for trading calculations.

Functions for: percentage changes, risk-reward ratios, Kelly criterion,
basis point conversions, and statistical helpers.
"""

import math


def pct_change(old: float, new: float) -> float:
    """Calculate percentage change from old to new."""
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100


def risk_reward_ratio(entry: float, stop_loss: float, take_profit: float) -> float:
    """Calculate risk-reward ratio.

    Returns:
        Ratio as a float (e.g., 2.0 means 2:1 reward-to-risk).
    """
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        return 0.0
    return reward / risk


def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Calculate Kelly criterion for optimal bet sizing.

    Args:
        win_rate: Probability of winning (0-1)
        avg_win: Average win amount
        avg_loss: Average loss amount (positive number)

    Returns:
        Kelly fraction (0-1). Negative means don't bet.
    """
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    kelly = (win_rate * b - (1 - win_rate)) / b
    return max(0.0, kelly)


def half_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Half-Kelly — conservative position sizing."""
    return kelly_criterion(win_rate, avg_win, avg_loss) / 2


def bps_to_pct(bps: float) -> float:
    """Convert basis points to percentage."""
    return bps / 100


def pct_to_bps(pct: float) -> float:
    """Convert percentage to basis points."""
    return pct * 100


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(value, max_val))


def round_to_tick(price: float, tick_size: float) -> float:
    """Round price to the nearest tick size."""
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 10)


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Calculate annualized Sharpe ratio from a list of returns.

    Args:
        returns: List of period returns (e.g., daily)
        risk_free_rate: Risk-free rate per period

    Returns:
        Annualized Sharpe ratio.
    """
    if len(returns) < 2:
        return 0.0

    excess = [r - risk_free_rate for r in returns]
    mean = sum(excess) / len(excess)
    variance = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(variance)

    if std == 0:
        return 0.0

    # Annualize (assuming daily returns)
    return (mean / std) * math.sqrt(365)


def max_drawdown(equity_curve: list[float]) -> float:
    """Calculate maximum drawdown from an equity curve.

    Returns:
        Maximum drawdown as a positive percentage.
    """
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return max_dd
