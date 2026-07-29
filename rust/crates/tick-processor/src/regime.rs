use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MarketRegime {
    StrongTrendUp,
    StrongTrendDown,
    Ranging,
    HighVolatility,
    Uncertain,
}

impl MarketRegime {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::StrongTrendUp => "STRONG_TREND_UP",
            Self::StrongTrendDown => "STRONG_TREND_DOWN",
            Self::Ranging => "RANGING",
            Self::HighVolatility => "HIGH_VOLATILITY",
            Self::Uncertain => "UNCERTAIN",
        }
    }
}

pub struct RegimeDetector {
    adx_threshold: f64,
    atr_vol_pct: f64,
}

impl RegimeDetector {
    pub fn new(adx_threshold: f64, atr_vol_pct: f64) -> Self {
        Self { adx_threshold, atr_vol_pct }
    }

    pub fn classify(&self, adx: f64, plus_di: f64, minus_di: f64, atr_pct: f64, in_bb_range: bool) -> MarketRegime {
        if atr_pct > self.atr_vol_pct { return MarketRegime::HighVolatility; }
        if adx > self.adx_threshold {
            return if plus_di > minus_di { MarketRegime::StrongTrendUp } else { MarketRegime::StrongTrendDown };
        }
        if in_bb_range { return MarketRegime::Ranging; }
        MarketRegime::Uncertain
    }
}

impl Default for RegimeDetector {
    fn default() -> Self { Self::new(25.0, 3.0) }
}
