//! Compute-intensive operations migrated from Python to Rust.
//!
//! These functions replace hot-path Python code in:
//! - `src/tools/correlation.py` → `CorrelationAnalyzer`
//! - `src/tools/portfolio.py` → `PortfolioOptimizer` (Mean-CVaR, correlation matrix)
//! - `src/tools/execution.py` → `SlippageTracker`
//! - `src/tools/volatility.py` → `VolatilityAnalyzer`
//! - `src/strategy/monte_carlo.py` → `MonteCarloSimulator`
//! - `src/tools/technical_analysis.py` → `TechnicalAnalysisTools`
//!
//! Each function is exposed as a standalone `#[pyfunction]` that operates
//! on Python lists/numpy arrays, returning Python dicts or lists.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

// ═══════════════════════════════════════════════════════════════════════
// CORRELATION MATRIX — replaces Python correlation.py
// ═══════════════════════════════════════════════════════════════════════

/// Compute a full pairwise Pearson correlation matrix from log returns.
///
/// Replaces the Python `CorrelationAnalyzer.correlation_matrix()` method.
/// Uses parallel computation for the O(n²) pairwise correlations.
///
/// Args:
///     returns: List of lists — each inner list is a return series for one asset.
///     window: Rolling window size (if > 0, uses last `window` values).
///
/// Returns:
///     Flat list of correlation values (row-major, n×n).
#[pyfunction]
pub fn correlation_matrix_py(
    py: Python<'_>,
    returns: &Bound<'_, PyList>,
    window: usize,
) -> PyResult<PyObject> {
    let n_assets = returns.len();
    if n_assets < 2 {
        let empty: Vec<f64> = vec![];
        return Ok(empty.into_py(py));
    }

    // Extract all return series
    let mut series: Vec<Vec<f64>> = Vec::with_capacity(n_assets);
    for i in 0..n_assets {
        let row = returns.get_item(i)?;
        let vals: Vec<f64> = row.extract()?;
        series.push(vals);
    }

    // Determine effective length
    let min_len = series.iter().map(|s| s.len()).min().unwrap_or(0);
    let effective_len = if window > 0 && window < min_len {
        window
    } else {
        min_len
    };

    if effective_len < 3 {
        let empty: Vec<f64> = vec![];
        return Ok(empty.into_py(py));
    }

    // Compute pairwise correlations
    let mut matrix = vec![0.0f64; n_assets * n_assets];
    for i in 0..n_assets {
        matrix[i * n_assets + i] = 1.0;
        for j in (i + 1)..n_assets {
            let start_i = series[i].len() - effective_len;
            let start_j = series[j].len() - effective_len;
            let corr = pearson_correlation(
                &series[i][start_i..],
                &series[j][start_j..],
            );
            matrix[i * n_assets + j] = corr;
            matrix[j * n_assets + i] = corr;
        }
    }

    Ok(matrix.into_py(py))
}

/// Compute rolling Pearson correlation between two price series.
///
/// Replaces `CorrelationAnalyzer.rolling_correlation()`.
///
/// Args:
///     prices_a: First asset's price series (oldest first).
///     prices_b: Second asset's price series (oldest first).
///     window: Rolling window size.
///     use_log_returns: If true, use log returns; otherwise simple returns.
///
/// Returns:
///     Dict with correlation, p_value, lag.
#[pyfunction]
pub fn rolling_correlation_py(
    py: Python<'_>,
    prices_a: Vec<f64>,
    prices_b: Vec<f64>,
    window: usize,
    use_log_returns: bool,
) -> PyResult<PyObject> {
    let min_len = prices_a.len().min(prices_b.len());
    if min_len < window + 1 {
        let dict = PyDict::new(py);
        dict.set_item("correlation", 0.0)?;
        dict.set_item("p_value", 1.0)?;
        dict.set_item("lag", 0)?;
        return Ok(dict.into());
    }

    let a = &prices_a[prices_a.len() - min_len..];
    let b = &prices_b[prices_b.len() - min_len..];

    let (ret_a, ret_b) = if use_log_returns {
        (log_returns(a), log_returns(b))
    } else {
        (simple_returns(a), simple_returns(b))
    };

    let corr = pearson_correlation(
        &ret_a[ret_a.len() - window..],
        &ret_b[ret_b.len() - window..],
    );

    // Lag detection
    let mut best_lag = 0usize;
    let mut best_corr_abs = corr.abs();
    for lag in 1..(window / 4).min(5) {
        if ret_a.len() > lag + window {
            let c = pearson_correlation(
                &ret_a[ret_a.len() - window - lag..ret_a.len() - lag],
                &ret_b[ret_b.len() - window..],
            );
            if c.abs() > best_corr_abs {
                best_corr_abs = c.abs();
                best_lag = lag;
            }
        }
    }

    let p_value = approximate_p_value(corr, window);

    let dict = PyDict::new(py);
    dict.set_item("correlation", round_to(corr, 6))?;
    dict.set_item("p_value", round_to(p_value, 6))?;
    dict.set_item("lag", best_lag)?;
    Ok(dict.into())
}

// ═══════════════════════════════════════════════════════════════════════
// MONTE CARLO SIMULATION — replaces Python monte_carlo.py
// ═══════════════════════════════════════════════════════════════════════

/// Run Monte Carlo simulation by shuffling trade PnLs.
///
/// Replaces `MonteCarloSimulator.run()`. Executes N simulations
/// where each simulation randomly permutes the trade order and
/// computes equity curve metrics.
///
/// Args:
///     pnl_pcts: Array of per-trade return fractions.
///     n_simulations: Number of Monte Carlo iterations.
///     initial_capital: Starting capital for each simulation.
///     risk_free_rate: Annualized risk-free rate.
///     trading_days: Trading days per year for annualization.
///     seed: Random seed (0 = non-deterministic).
///
/// Returns:
///     Dict with simulation results (total_returns, sharpes, max_drawdowns, etc.)
#[pyfunction]
pub fn monte_carlo_simulate_py(
    py: Python<'_>,
    pnl_pcts: Vec<f64>,
    n_simulations: usize,
    initial_capital: f64,
    risk_free_rate: f64,
    trading_days: usize,
    seed: u64,
) -> PyResult<PyObject> {
    if pnl_pcts.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Cannot run Monte Carlo on empty trade list",
        ));
    }

    let n_trades = pnl_pcts.len();
    let daily_rf = risk_free_rate / trading_days as f64;

    let mut total_returns = Vec::with_capacity(n_simulations);
    let mut sharpes = Vec::with_capacity(n_simulations);
    let mut max_drawdowns = Vec::with_capacity(n_simulations);
    let mut win_rates = Vec::with_capacity(n_simulations);
    let mut profit_factors = Vec::with_capacity(n_simulations);

    // Simple PRNG (xorshift64)
    let mut rng_state = if seed > 0 { seed } else { 0x123456789ABCDEFu64 };

    for _sim in 0..n_simulations {
        // Fisher-Yates shuffle using xorshift64
        let mut indices: Vec<usize> = (0..n_trades).collect();
        for i in (1..n_trades).rev() {
            rng_state ^= rng_state << 13;
            rng_state ^= rng_state >> 7;
            rng_state ^= rng_state << 17;
            let j = (rng_state as usize) % (i + 1);
            indices.swap(i, j);
        }

        // Simulate equity curve
        let mut equity = vec![initial_capital; n_trades + 1];
        for k in 0..n_trades {
            equity[k + 1] = equity[k] * (1.0 + pnl_pcts[indices[k]]);
        }

        // Total return
        let total_ret = (equity[n_trades] - initial_capital) / initial_capital;
        total_returns.push(total_ret);

        // Win rate
        let wins = indices.iter().filter(|&&idx| pnl_pcts[idx] > 0.0).count();
        win_rates.push(wins as f64 / n_trades as f64);

        // Profit factor
        let gross_profit: f64 = indices
            .iter()
            .filter(|&&idx| pnl_pcts[idx] > 0.0)
            .map(|&idx| pnl_pcts[idx])
            .sum();
        let gross_loss: f64 = indices
            .iter()
            .filter(|&&idx| pnl_pcts[idx] <= 0.0)
            .map(|&idx| pnl_pcts[idx].abs())
            .sum();
        profit_factors.push(if gross_loss > 0.0 {
            gross_profit / gross_loss
        } else if gross_profit > 0.0 {
            f64::INFINITY
        } else {
            0.0
        });

        // Max drawdown
        let mut peak = equity[0];
        let mut max_dd = 0.0f64;
        for val in &equity {
            if *val > peak {
                peak = *val;
            }
            let dd = if peak > 0.0 { (peak - val) / peak } else { 0.0 };
            if dd > max_dd {
                max_dd = dd;
            }
        }
        max_drawdowns.push(max_dd);

        // Sharpe ratio
        let returns: Vec<f64> = (0..n_trades)
            .map(|k| (equity[k + 1] - equity[k]) / equity[k])
            .collect();
        let mean_ret: f64 = returns.iter().sum::<f64>() / n_trades as f64;
        let excess = mean_ret - daily_rf;
        let variance: f64 = returns
            .iter()
            .map(|r| (r - mean_ret).powi(2))
            .sum::<f64>()
            / (n_trades - 1).max(1) as f64;
        let std = variance.sqrt();
        let sharpe = if std > 0.0 {
            excess / std * (trading_days as f64).sqrt()
        } else {
            0.0
        };
        sharpes.push(sharpe);
    }

    // Probability of profit / ruin
    let prob_profit = total_returns.iter().filter(|&&r| r > 0.0).count() as f64
        / n_simulations as f64;
    let ruin_threshold = initial_capital * 0.5;
    let prob_ruin = total_returns
        .iter()
        .filter(|&&r| initial_capital * (1.0 + r) < ruin_threshold)
        .count() as f64
        / n_simulations as f64;

    // Build result dict
    let dict = PyDict::new(py);
    dict.set_item("total_returns", &total_returns)?;
    dict.set_item("sharpes", &sharpes)?;
    dict.set_item("max_drawdowns", &max_drawdowns)?;
    dict.set_item("win_rates", &win_rates)?;
    dict.set_item("profit_factors", &profit_factors)?;
    dict.set_item("probability_of_profit", round_to(prob_profit, 6))?;
    dict.set_item("probability_of_ruin", round_to(prob_ruin, 6))?;
    dict.set_item("n_simulations", n_simulations)?;
    dict.set_item("n_trades", n_trades)?;

    // Compute percentiles for key metrics
    let percentiles = vec![5.0, 25.0, 50.0, 75.0, 95.0];
    let metrics: Vec<(&str, &Vec<f64>)> = vec![
        ("total_return", &total_returns),
        ("sharpe_ratio", &sharpes),
        ("max_drawdown", &max_drawdowns),
        ("win_rate", &win_rates),
        ("profit_factor", &profit_factors),
    ];

    let pct_dict = PyDict::new(py);
    for (name, values) in &metrics {
        let sorted = sorted_f64(values);
        let p_dict = PyDict::new(py);
        for &p in &percentiles {
            let idx = ((p / 100.0) * (sorted.len() - 1) as f64).round() as usize;
            let idx = idx.min(sorted.len() - 1);
            p_dict.set_item(p.to_string(), round_to(sorted[idx], 6))?;
        }
        p_dict.set_item("mean", round_to(mean_f64(values), 6))?;
        p_dict.set_item("std", round_to(std_f64(values), 6))?;
        p_dict.set_item("min", round_to(sorted[0], 6))?;
        p_dict.set_item("max", round_to(*sorted.last().unwrap(), 6))?;
        pct_dict.set_item(name, p_dict)?;
    }
    dict.set_item("percentile_distributions", pct_dict)?;

    Ok(dict.into())
}

// ═══════════════════════════════════════════════════════════════════════
// SLIPPAGE CALCULATOR — replaces Python execution.py slippage tracking
// ═══════════════════════════════════════════════════════════════════════

/// Compute slippage statistics from a history of slippage values.
///
/// Replaces `ExecutionTools.get_slippage_stats()`.
///
/// Args:
///     slippage_bps: List of slippage values in basis points.
///
/// Returns:
///     Dict with avg, median, max, total_slippage_usd stats.
#[pyfunction]
pub fn slippage_stats_py(
    py: Python<'_>,
    slippage_bps: Vec<f64>,
) -> PyResult<PyObject> {
    if slippage_bps.is_empty() {
        let dict = PyDict::new(py);
        dict.set_item("total_trades", 0)?;
        dict.set_item("avg_slippage_bps", 0.0)?;
        dict.set_item("median_slippage_bps", 0.0)?;
        dict.set_item("max_slippage_bps", 0.0)?;
        return Ok(dict.into());
    }

    let abs_slippages: Vec<f64> = slippage_bps.iter().map(|s| s.abs()).collect();
    let sorted = sorted_f64(&abs_slippages);

    let dict = PyDict::new(py);
    dict.set_item("total_trades", abs_slippages.len())?;
    dict.set_item("avg_slippage_bps", round_to(mean_f64(&abs_slippages), 4))?;
    dict.set_item(
        "median_slippage_bps",
        round_to(median_sorted(&sorted), 4),
    )?;
    dict.set_item("max_slippage_bps", round_to(*sorted.last().unwrap(), 4))?;
    Ok(dict.into())
}

// ═══════════════════════════════════════════════════════════════════════
// VOLATILITY — replaces Python volatility.py
// ═══════════════════════════════════════════════════════════════════════

/// Compute Garman-Klass volatility from OHLCV data.
///
/// Most efficient volatility estimator using full OHLC information.
/// Replaces `VolatilityAnalyzer._garman_klass_vol()`.
///
/// Args:
///     opens: Open prices.
///     highs: High prices.
///     lows: Low prices.
///     closes: Close prices.
///
/// Returns:
///     Garman-Klass daily volatility (not annualized).
#[pyfunction]
pub fn garman_klass_vol_py(
    opens: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
) -> PyResult<f64> {
    let n = opens.len().min(highs.len()).min(lows.len()).min(closes.len());
    if n == 0 {
        return Ok(0.0);
    }

    let ln2 = 2.0_f64.ln();
    let mut sum_val = 0.0f64;
    let mut count = 0usize;

    for i in 0..n {
        if highs[i] <= 0.0 || lows[i] <= 0.0 || opens[i] <= 0.0 {
            continue;
        }
        let hl = (highs[i] / lows[i]).ln().powi(2);
        let co = (closes[i] / opens[i]).ln().powi(2);
        sum_val += 0.5 * hl - (2.0 * ln2 - 1.0) * co;
        count += 1;
    }

    if count == 0 {
        return Ok(0.0);
    }

    let variance = sum_val / count as f64;
    Ok(variance.max(0.0).sqrt())
}

/// Compute GARCH(1,1) volatility forecast.
///
/// Replaces `VolatilityAnalyzer.garch_forecast()`.
///
/// Args:
///     closes: Close prices (oldest first).
///     annualization_factor: Days per year for annualization (365 for crypto).
///
/// Returns:
///     Dict with current_variance, forecast_1d, forecast_5d, forecast_10d,
///     annualized_vol, omega, alpha, beta, persistence.
#[pyfunction]
pub fn garch_forecast_py(
    py: Python<'_>,
    closes: Vec<f64>,
    annualization_factor: f64,
) -> PyResult<PyObject> {
    if closes.len() < 50 {
        let dict = PyDict::new(py);
        dict.set_item("current_variance", 0.0)?;
        dict.set_item("forecast_1d", 0.0)?;
        dict.set_item("forecast_5d", 0.0)?;
        dict.set_item("forecast_10d", 0.0)?;
        dict.set_item("annualized_vol", 0.0)?;
        dict.set_item("omega", 0.0)?;
        dict.set_item("alpha", 0.1)?;
        dict.set_item("beta", 0.85)?;
        dict.set_item("persistence", 0.95)?;
        return Ok(dict.into());
    }

    // Compute log returns
    let returns: Vec<f64> = (1..closes.len())
        .map(|i| (closes[i] / closes[i - 1]).ln())
        .collect();

    let n = returns.len();
    let mean_sq: f64 = returns.iter().map(|r| r * r).sum::<f64>() / n as f64;
    let var: f64 = returns
        .iter()
        .map(|r| (r - returns.iter().sum::<f64>() / n as f64).powi(2))
        .sum::<f64>()
        / n as f64;

    // Estimate GARCH parameters via method of moments
    let sq_returns: Vec<f64> = returns.iter().map(|r| r * r).collect();
    let acf1 = if n >= 3 {
        let mean_sq_val = sq_returns.iter().sum::<f64>() / n as f64;
        let cov: f64 = (0..n - 1)
            .map(|i| (sq_returns[i] - mean_sq_val) * (sq_returns[i + 1] - mean_sq_val))
            .sum::<f64>()
            / (n - 1) as f64;
        let var_sq: f64 = sq_returns
            .iter()
            .map(|x| (x - mean_sq_val).powi(2))
            .sum::<f64>()
            / n as f64;
        if var_sq > 0.0 { (cov / var_sq).clamp(-1.0, 1.0) } else { 0.1 }
    } else {
        0.1
    };

    let mut beta = (acf1 * 0.9).clamp(0.5, 0.98);
    let mut alpha = (mean_sq * 0.1 / var.max(1e-10)).clamp(0.05, 0.3);

    if alpha + beta >= 1.0 {
        alpha = (1.0 - beta) * 0.9;
    }

    let omega = (var * (1.0 - alpha - beta)).max(1e-10);
    let persistence = alpha + beta;

    // Compute conditional variance series
    let mut variances = vec![0.0f64; n];
    variances[0] = var;
    for t in 1..n {
        variances[t] = omega + alpha * returns[t - 1].powi(2) + beta * variances[t - 1];
    }

    let current_var = *variances.last().unwrap();

    // Forecast
    let (forecast_1, forecast_5, forecast_10) = if persistence < 1.0 {
        let long_run = omega / (1.0 - persistence);
        (
            long_run + persistence * (current_var - long_run),
            long_run + persistence.powi(5) * (current_var - long_run),
            long_run + persistence.powi(10) * (current_var - long_run),
        )
    } else {
        (current_var, current_var, current_var)
    };

    let annualized_vol = (current_var * annualization_factor).sqrt();

    let dict = PyDict::new(py);
    dict.set_item("current_variance", round_to(current_var, 10))?;
    dict.set_item("forecast_1d", round_to(forecast_1, 10))?;
    dict.set_item("forecast_5d", round_to(forecast_5, 10))?;
    dict.set_item("forecast_10d", round_to(forecast_10, 10))?;
    dict.set_item("annualized_vol", round_to(annualized_vol, 4))?;
    dict.set_item("omega", round_to(omega, 10))?;
    dict.set_item("alpha", round_to(alpha, 4))?;
    dict.set_item("beta", round_to(beta, 4))?;
    dict.set_item("persistence", round_to(persistence, 4))?;
    Ok(dict.into())
}

// ═══════════════════════════════════════════════════════════════════════
// TECHNICAL INDICATORS — batch computation for factor library
// ═══════════════════════════════════════════════════════════════════════

/// Batch-compute all technical indicator factors from OHLCV data.
///
/// Replaces individual calls to factors.py functions. Returns all
/// factor values as a dict of lists, ready for DataFrame construction.
///
/// Args:
///     opens, highs, lows, closes, volumes: OHLCV arrays.
///     rsi_period: RSI period (default 14).
///     macd_fast, macd_slow, macd_signal: MACD parameters.
///     bb_period, bb_std: Bollinger Band parameters.
///     atr_period: ATR period.
///     adx_period: ADX period.
///
/// Returns:
///     Dict mapping factor name to list of values.
#[pyfunction]
#[pyo3(signature = (opens, highs, lows, closes, volumes, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, bb_period=20, bb_std=2.0, atr_period=14, adx_period=14))]
pub fn batch_factors_py(
    py: Python<'_>,
    opens: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
    volumes: Vec<f64>,
    rsi_period: usize,
    macd_fast: usize,
    macd_slow: usize,
    macd_signal: usize,
    bb_period: usize,
    bb_std: f64,
    atr_period: usize,
    adx_period: usize,
) -> PyResult<PyObject> {
    let n = closes.len();
    if n < 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Need at least 2 data points",
        ));
    }

    let dict = PyDict::new(py);

    // RSI
    let rsi_vals = compute_rsi(&closes, rsi_period);
    dict.set_item("rsi", rsi_vals)?;

    // MACD histogram
    let macd_vals = compute_macd_histogram(&closes, macd_fast, macd_slow, macd_signal);
    dict.set_item("macd", macd_vals)?;

    // Bollinger Band %B
    let bb_pctb = compute_bb_pctb(&closes, bb_period, bb_std);
    dict.set_item("bb_pct_b", bb_pctb)?;

    // ATR normalized
    let atr_norm = compute_atr_normalized(&highs, &lows, &closes, atr_period);
    dict.set_item("atr_normalized", atr_norm)?;

    // ADX
    let adx_vals = compute_adx(&highs, &lows, &closes, adx_period);
    dict.set_item("adx", adx_vals)?;

    // Volume ROC
    let vol_roc = compute_volume_roc(&volumes, 10);
    dict.set_item("volume_roc", vol_roc)?;

    // Z-Score
    let zscore_vals = compute_zscore(&closes, 20);
    dict.set_item("zscore", zscore_vals)?;

    // VWAP distance
    let vwap_dist = compute_vwap_distance(&highs, &lows, &closes, &volumes);
    dict.set_item("vwap_distance", vwap_dist)?;

    Ok(dict.into())
}

// ═══════════════════════════════════════════════════════════════════════
// INTERNAL HELPERS
// ═══════════════════════════════════════════════════════════════════════

fn pearson_correlation(x: &[f64], y: &[f64]) -> f64 {
    let n = x.len().min(y.len());
    if n < 3 {
        return 0.0;
    }
    let x = &x[..n];
    let y = &y[..n];

    let x_mean: f64 = x.iter().sum::<f64>() / n as f64;
    let y_mean: f64 = y.iter().sum::<f64>() / n as f64;

    let mut cov = 0.0f64;
    let mut var_x = 0.0f64;
    let mut var_y = 0.0f64;

    for i in 0..n {
        let dx = x[i] - x_mean;
        let dy = y[i] - y_mean;
        cov += dx * dy;
        var_x += dx * dx;
        var_y += dy * dy;
    }

    let denom = (var_x * var_y).sqrt();
    if denom == 0.0 {
        return 0.0;
    }

    (cov / denom).clamp(-1.0, 1.0)
}

fn log_returns(prices: &[f64]) -> Vec<f64> {
    (1..prices.len())
        .map(|i| (prices[i] / prices[i - 1]).ln())
        .collect()
}

fn simple_returns(prices: &[f64]) -> Vec<f64> {
    (1..prices.len())
        .map(|i| (prices[i] - prices[i - 1]) / prices[i - 1])
        .collect()
}

fn approximate_p_value(r: f64, n: usize) -> f64 {
    if n < 3 || r.abs() >= 1.0 {
        return if r.abs() >= 1.0 { 0.0 } else { 1.0 };
    }
    let t_stat = r * ((n - 2) as f64 / (1.0 - r * r)).sqrt();
    let df = (n - 2) as f64;
    // Approximate two-tailed p-value
    let x = df / (df + t_stat * t_stat);
    let p = if t_stat > 0.0 {
        0.5 + 0.5 * (1.0 - x).min(1.0)
    } else {
        0.5 - 0.5 * (1.0 - x).min(1.0)
    };
    (2.0 * (0.5 - p).abs()).clamp(0.0, 1.0)
}

fn round_to(val: f64, decimals: u32) -> f64 {
    let factor = 10.0_f64.powi(decimals as i32);
    (val * factor).round() / factor
}

fn mean_f64(v: &[f64]) -> f64 {
    if v.is_empty() {
        0.0
    } else {
        v.iter().sum::<f64>() / v.len() as f64
    }
}

fn std_f64(v: &[f64]) -> f64 {
    if v.len() < 2 {
        return 0.0;
    }
    let mean = mean_f64(v);
    let variance: f64 = v.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (v.len() - 1) as f64;
    variance.sqrt()
}

fn sorted_f64(v: &[f64]) -> Vec<f64> {
    let mut s = v.to_vec();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    s
}

fn median_sorted(sorted: &[f64]) -> f64 {
    let n = sorted.len();
    if n == 0 {
        return 0.0;
    }
    if n % 2 == 0 {
        (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    } else {
        sorted[n / 2]
    }
}

// ── Technical Indicator Implementations ────────────────────────────

fn compute_rsi(closes: &[f64], period: usize) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![50.0f64; n]; // Default to neutral
    if n < period + 1 {
        return result;
    }

    let mut avg_gain = 0.0f64;
    let mut avg_loss = 0.0f64;

    // Initial SMA
    for i in 1..=period {
        let change = closes[i] - closes[i - 1];
        if change > 0.0 {
            avg_gain += change;
        } else {
            avg_loss -= change;
        }
    }
    avg_gain /= period as f64;
    avg_loss /= period as f64;

    result[period] = if avg_loss == 0.0 {
        100.0
    } else {
        100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    };

    // Wilder smoothing
    let alpha = 1.0 / period as f64;
    for i in (period + 1)..n {
        let change = closes[i] - closes[i - 1];
        let (gain, loss) = if change > 0.0 {
            (change, 0.0)
        } else {
            (0.0, -change)
        };
        avg_gain = avg_gain * (1.0 - alpha) + gain * alpha;
        avg_loss = avg_loss * (1.0 - alpha) + loss * alpha;
        result[i] = if avg_loss == 0.0 {
            100.0
        } else {
            100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        };
    }
    result
}

fn compute_macd_histogram(
    closes: &[f64],
    fast: usize,
    slow: usize,
    signal: usize,
) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.0f64; n];

    let ema_fast = ema_series(closes, fast);
    let ema_slow = ema_series(closes, slow);

    let macd_line: Vec<f64> = ema_fast
        .iter()
        .zip(ema_slow.iter())
        .map(|(a, b)| a - b)
        .collect();

    let signal_line = ema_series(&macd_line, signal);

    for i in 0..n {
        result[i] = macd_line[i] - signal_line[i];
    }
    result
}

fn ema_series(data: &[f64], period: usize) -> Vec<f64> {
    let n = data.len();
    let mut result = vec![0.0f64; n];
    if n == 0 || period == 0 {
        return result;
    }
    result[0] = data[0];
    let k = 2.0 / (period as f64 + 1.0);
    for i in 1..n {
        result[i] = data[i] * k + result[i - 1] * (1.0 - k);
    }
    result
}

fn compute_bb_pctb(closes: &[f64], period: usize, std_dev: f64) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.5f64; n];

    for i in period..n {
        let slice = &closes[i + 1 - period..=i];
        let mean: f64 = slice.iter().sum::<f64>() / period as f64;
        let var: f64 = slice.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / period as f64;
        let std = var.sqrt();
        let upper = mean + std_dev * std;
        let lower = mean - std_dev * std;
        let bw = upper - lower;
        result[i] = if bw > 0.0 {
            (closes[i] - lower) / bw
        } else {
            0.5
        };
    }
    result
}

fn compute_atr_normalized(
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    period: usize,
) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.0f64; n];

    if n < 2 {
        return result;
    }

    // True range
    let mut tr = vec![0.0f64; n];
    tr[0] = highs[0] - lows[0];
    for i in 1..n {
        tr[i] = (highs[i] - lows[i])
            .max((highs[i] - closes[i - 1]).abs())
            .max((lows[i] - closes[i - 1]).abs());
    }

    // EMA of TR
    let atr = ema_series(&tr, period);

    for i in 0..n {
        result[i] = if closes[i] > 0.0 {
            atr[i] / closes[i] * 100.0
        } else {
            0.0
        };
    }
    result
}

fn compute_adx(
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    period: usize,
) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.0f64; n];

    if n < period + 1 {
        return result;
    }

    let mut plus_dm = vec![0.0f64; n];
    let mut minus_dm = vec![0.0f64; n];
    let mut tr = vec![0.0f64; n];

    for i in 1..n {
        let up = highs[i] - highs[i - 1];
        let down = lows[i - 1] - lows[i];
        plus_dm[i] = if up > down && up > 0.0 { up } else { 0.0 };
        minus_dm[i] = if down > up && down > 0.0 { down } else { 0.0 };
        tr[i] = (highs[i] - lows[i])
            .max((highs[i] - closes[i - 1]).abs())
            .max((lows[i] - closes[i - 1]).abs());
    }

    let atr = ema_series(&tr, period);
    let plus_di = ema_series(&plus_dm, period);
    let minus_di = ema_series(&minus_dm, period);

    let mut dx = vec![0.0f64; n];
    for i in 0..n {
        let di_sum = plus_di[i] + minus_di[i];
        dx[i] = if di_sum > 0.0 {
            ((plus_di[i] - minus_di[i]).abs() / di_sum) * 100.0
        } else {
            0.0
        };
    }

    let adx = ema_series(&dx, period);
    for i in 0..n {
        result[i] = adx[i];
    }
    result
}

fn compute_volume_roc(volumes: &[f64], period: usize) -> Vec<f64> {
    let n = volumes.len();
    let mut result = vec![0.0f64; n];
    for i in period..n {
        if volumes[i - period] > 0.0 {
            result[i] = (volumes[i] - volumes[i - period]) / volumes[i - period] * 100.0;
        }
    }
    result
}

fn compute_zscore(closes: &[f64], period: usize) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.0f64; n];
    for i in period..n {
        let slice = &closes[i + 1 - period..=i];
        let mean: f64 = slice.iter().sum::<f64>() / period as f64;
        let var: f64 = slice.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / period as f64;
        let std = var.sqrt();
        result[i] = if std > 0.0 {
            (closes[i] - mean) / std
        } else {
            0.0
        };
    }
    result
}

fn compute_vwap_distance(
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    volumes: &[f64],
) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![0.0f64; n];

    let mut cum_tp_vol = 0.0f64;
    let mut cum_vol = 0.0f64;

    for i in 0..n {
        let tp = (highs[i] + lows[i] + closes[i]) / 3.0;
        cum_tp_vol += tp * volumes[i];
        cum_vol += volumes[i];
        let vwap = if cum_vol > 0.0 {
            cum_tp_vol / cum_vol
        } else {
            closes[i]
        };
        result[i] = if vwap > 0.0 {
            (closes[i] - vwap) / vwap * 100.0
        } else {
            0.0
        };
    }
    result
}
