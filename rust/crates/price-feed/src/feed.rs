//! Price feed — fetches prices from multiple external APIs.

use chrono::Utc;
use tracing::{debug, info, warn};

use crate::types::{PriceObservation, PriceSource};

/// Configuration for the price feed.
#[derive(Debug, Clone)]
pub struct FeedConfig {
    /// CoinGecko API key (optional, for pro tier).
    pub coingecko_api_key: Option<String>,
    /// CoinMarketCap API key.
    pub coinmarketcap_api_key: Option<String>,
    /// Binance API base URL.
    pub binance_url: String,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
}

impl Default for FeedConfig {
    fn default() -> Self {
        Self {
            coingecko_api_key: None,
            coinmarketcap_api_key: None,
            binance_url: "https://api.binance.com".to_string(),
            timeout_secs: 10,
        }
    }
}

/// Price feed — fetches prices from external APIs.
pub struct PriceFeed {
    config: FeedConfig,
    http: reqwest::Client,
}

impl PriceFeed {
    /// Create a new price feed.
    pub fn new(config: FeedConfig) -> Self {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(config.timeout_secs))
            .build()
            .expect("Failed to create HTTP client");

        Self { config, http }
    }

    /// Fetch price from CoinGecko.
    pub async fn fetch_coingecko(
        &self,
        symbol: &str,
    ) -> Result<PriceObservation, String> {
        let coin_id = symbol_to_coingecko_id(symbol);
        let url = format!(
            "https://api.coingecko.com/api/v3/simple/price?ids={}&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true",
            coin_id
        );

        let mut req = self.http.get(&url);
        if let Some(ref key) = self.config.coingecko_api_key {
            req = req.header("x-cg-pro-api-key", key);
        }

        let resp: serde_json::Value = req
            .send()
            .await
            .map_err(|e| format!("CoinGecko HTTP error: {e}"))?
            .json()
            .await
            .map_err(|e| format!("CoinGecko JSON error: {e}"))?;

        let price = resp
            .get(&coin_id)
            .and_then(|v| v.get("usd"))
            .and_then(|v| v.as_f64())
            .ok_or_else(|| "Missing price in CoinGecko response".to_string())?;

        let volume = resp
            .get(&coin_id)
            .and_then(|v| v.get("usd_24h_vol"))
            .and_then(|v| v.as_f64());

        let change = resp
            .get(&coin_id)
            .and_then(|v| v.get("usd_24h_change"))
            .and_then(|v| v.as_f64());

        Ok(PriceObservation {
            source: PriceSource::CoinGecko,
            symbol: symbol.to_string(),
            price_usd: price,
            volume_24h_usd: volume,
            change_24h_pct: change,
            observed_at: Utc::now(),
            max_age_secs: 60,
        })
    }

    /// Fetch price from Binance.
    pub async fn fetch_binance(&self, symbol: &str) -> Result<PriceObservation, String> {
        let binance_symbol = format!("{}USDT", symbol.to_uppercase());
        let url = format!(
            "{}/api/v3/ticker/24hr?symbol={}",
            self.config.binance_url, binance_symbol
        );

        let resp: serde_json::Value = self
            .http
            .get(&url)
            .send()
            .await
            .map_err(|e| format!("Binance HTTP error: {e}"))?
            .json()
            .await
            .map_err(|e| format!("Binance JSON error: {e}"))?;

        let price = resp
            .get("lastPrice")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .ok_or_else(|| "Missing price in Binance response".to_string())?;

        let volume = resp
            .get("quoteVolume")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok());

        let change = resp
            .get("priceChangePercent")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok());

        Ok(PriceObservation {
            source: PriceSource::Binance,
            symbol: symbol.to_string(),
            price_usd: price,
            volume_24h_usd: volume,
            change_24h_pct: change,
            observed_at: Utc::now(),
            max_age_secs: 30,
        })
    }

    /// Fetch price from CoinMarketCap.
    pub async fn fetch_coinmarketcap(
        &self,
        symbol: &str,
    ) -> Result<PriceObservation, String> {
        let api_key = self
            .config
            .coinmarketcap_api_key
            .as_ref()
            .ok_or_else(|| "CoinMarketCap API key not configured".to_string())?;

        let url = format!(
            "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol={}&convert=USD",
            symbol.to_uppercase()
        );

        let resp: serde_json::Value = self
            .http
            .get(&url)
            .header("X-CMC_PRO_API_KEY", api_key)
            .send()
            .await
            .map_err(|e| format!("CMC HTTP error: {e}"))?
            .json()
            .await
            .map_err(|e| format!("CMC JSON error: {e}"))?;

        let price = resp
            .get("data")
            .and_then(|d| d.get(&symbol.to_uppercase()))
            .and_then(|arr| arr.as_array())
            .and_then(|arr| arr.first())
            .and_then(|v| v.get("quote"))
            .and_then(|q| q.get("USD"))
            .and_then(|u| u.get("price"))
            .and_then(|p| p.as_f64())
            .ok_or_else(|| "Missing price in CMC response".to_string())?;

        Ok(PriceObservation {
            source: PriceSource::CoinMarketCap,
            symbol: symbol.to_string(),
            price_usd: price,
            volume_24h_usd: None,
            change_24h_pct: None,
            observed_at: Utc::now(),
            max_age_secs: 60,
        })
    }

    /// Fetch prices from all configured sources in parallel.
    pub async fn fetch_all(&self, symbol: &str) -> Vec<PriceObservation> {
        let (cg, bin, cmc) = tokio::join!(
            self.fetch_coingecko(symbol),
            self.fetch_binance(symbol),
            self.fetch_coinmarketcap(symbol),
        );

        let mut observations = Vec::new();

        if let Ok(obs) = cg {
            observations.push(obs);
        }
        if let Ok(obs) = bin {
            observations.push(obs);
        }
        if let Ok(obs) = cmc {
            observations.push(obs);
        }

        observations
    }
}

/// Map a token symbol to its CoinGecko coin ID.
fn symbol_to_coingecko_id(symbol: &str) -> &str {
    match symbol.to_uppercase().as_str() {
        "BTC" | "WBTC" => "bitcoin",
        "ETH" | "WETH" => "ethereum",
        "SOL" => "solana",
        "BNB" => "binancecoin",
        "MATIC" | "WMATIC" => "matic-network",
        "USDC" => "usd-coin",
        "USDT" => "tether",
        "DAI" => "dai",
        "LINK" => "chainlink",
        "UNI" => "uniswap",
        "AAVE" => "aave",
        "ARB" => "arbitrum",
        "OP" => "optimism",
        "AVAX" => "avalanche-2",
        _ => symbol.to_lowercase().as_str(),
    }
}
