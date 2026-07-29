/// Technical indicators in pure Rust — zero dependencies, maximum speed.

/// RSI — Relative Strength Index (Wilder smoothing)
pub fn rsi(closes: &[f64], period: usize) -> f64 {
    if closes.len() < period + 1 { return 50.0; }
    let mut gains = 0.0;
    let mut losses = 0.0;
    for i in (closes.len() - period)..closes.len() {
        let change = closes[i] - closes[i - 1];
        if change > 0.0 { gains += change; } else { losses -= change; }
    }
    let avg_gain = gains / period as f64;
    let avg_loss = losses / period as f64;
    if avg_loss == 0.0 { return 100.0; }
    let rs = avg_gain / avg_loss;
    100.0 - (100.0 / (1.0 + rs))
}

/// EMA — Exponential Moving Average
pub fn ema(closes: &[f64], period: usize) -> Vec<f64> {
    if closes.is_empty() || period == 0 { return vec![]; }
    let k = 2.0 / (period as f64 + 1.0);
    let mut result = Vec::with_capacity(closes.len());
    result.push(closes[0]);
    for i in 1..closes.len() {
        let val = closes[i] * k + result[i - 1] * (1.0 - k);
        result.push(val);
    }
    result
}

/// MACD — (macd_line, signal_line, histogram)
pub fn macd(closes: &[f64]) -> (f64, f64, f64) {
    if closes.len() < 26 { return (0.0, 0.0, 0.0); }
    let ema12 = ema(closes, 12);
    let ema26 = ema(closes, 26);
    let macd_line: Vec<f64> = ema12.iter().zip(ema26.iter()).map(|(a, b)| a - b).collect();
    let signal = ema(&macd_line, 9);
    let m = *macd_line.last().unwrap_or(&0.0);
    let s = *signal.last().unwrap_or(&0.0);
    (m, s, m - s)
}

/// Bollinger Bands — (upper, middle, lower)
pub fn bollinger(closes: &[f64], period: usize, std_dev: f64) -> (f64, f64, f64) {
    if closes.len() < period { return (0.0, 0.0, 0.0); }
    let slice = &closes[closes.len() - period..];
    let mean: f64 = slice.iter().sum::<f64>() / period as f64;
    let variance: f64 = slice.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / period as f64;
    let std = variance.sqrt();
    (mean + std_dev * std, mean, mean - std_dev * std)
}

/// ATR — Average True Range
pub fn atr(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> f64 {
    if highs.len() < period + 1 { return 0.0; }
    let mut tr_sum = 0.0;
    for i in (highs.len() - period)..highs.len() {
        let tr = (highs[i] - lows[i])
            .max((highs[i] - closes[i - 1]).abs())
            .max((lows[i] - closes[i - 1]).abs());
        tr_sum += tr;
    }
    tr_sum / period as f64
}

/// ADX — Average Directional Index
pub fn adx(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> (f64, f64, f64) {
    if highs.len() < period + 1 { return (0.0, 0.0, 0.0); }
    let mut plus_dm = 0.0;
    let mut minus_dm = 0.0;
    let mut tr_sum = 0.0;

    for i in (highs.len() - period)..highs.len() {
        let up = highs[i] - highs[i - 1];
        let down = lows[i - 1] - lows[i];
        if up > down && up > 0.0 { plus_dm += up; }
        if down > up && down > 0.0 { minus_dm += down; }
        let tr = (highs[i] - lows[i])
            .max((highs[i] - closes[i - 1]).abs())
            .max((lows[i] - closes[i - 1]).abs());
        tr_sum += tr;
    }

    let plus_di = if tr_sum > 0.0 { (plus_dm / tr_sum) * 100.0 } else { 0.0 };
    let minus_di = if tr_sum > 0.0 { (minus_dm / tr_sum) * 100.0 } else { 0.0 };
    let dx = if plus_di + minus_di > 0.0 {
        ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100.0
    } else { 0.0 };

    (dx, plus_di, minus_di)
}

/// VWAP — Volume Weighted Average Price
pub fn vwap(highs: &[f64], lows: &[f64], closes: &[f64], volumes: &[f64]) -> f64 {
    let n = highs.len().min(lows.len()).min(closes.len()).min(volumes.len());
    if n == 0 { return 0.0; }
    let mut tp_vol = 0.0;
    let mut vol_sum = 0.0;
    for i in 0..n {
        let tp = (highs[i] + lows[i] + closes[i]) / 3.0;
        tp_vol += tp * volumes[i];
        vol_sum += volumes[i];
    }
    if vol_sum == 0.0 { 0.0 } else { tp_vol / vol_sum }
}
