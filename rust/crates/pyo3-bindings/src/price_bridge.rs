//! PyO3 bridge for the price feed.
//!
//! Exposes oracle price aggregation and TWAP computation to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_price_feed::aggregator::{AggregatorConfig, PriceAggregator};
use tsar_price_feed::feed::{FeedConfig, PriceFeed};
use tsar_price_feed::types::PriceSource;

/// Python-visible price feed with aggregation.
#[pyclass(name = "PriceFeed")]
pub struct PyPriceFeed {
    feed: PriceFeed,
    aggregator: PriceAggregator,
}

#[pymethods]
impl PyPriceFeed {
    /// Create a new price feed.
    ///
    /// Args:
    ///     coingecko_api_key: Optional CoinGecko API key.
    ///     coinmarketcap_api_key: Optional CoinMarketCap API key.
    #[new]
    #[pyo3(signature = (coingecko_api_key=None, coinmarketcap_api_key=None))]
    fn new(coingecko_api_key: Option<&str>, coinmarketcap_api_key: Option<&str>) -> Self {
        let feed_config = FeedConfig {
            coingecko_api_key: coingecko_api_key.map(|s| s.to_string()),
            coinmarketcap_api_key: coinmarketcap_api_key.map(|s| s.to_string()),
            ..Default::default()
        };
        let agg_config = AggregatorConfig::default();

        Self {
            feed: PriceFeed::new(feed_config),
            aggregator: PriceAggregator::new(agg_config),
        }
    }

    /// Fetch and aggregate price from all sources.
    ///
    /// Args:
    ///     symbol: Token symbol (e.g., "ETH", "BTC").
    ///
    /// Returns a dict with aggregated price data.
    fn get_price(&mut self, symbol: &str) -> PyResult<PyObject> {
        // Fetch from all sources
        let observations = RUNTIME.block_on(self.feed.fetch_all(symbol));

        if observations.is_empty() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Failed to fetch price from any source"
            ));
        }

        // Add to aggregator
        for obs in &observations {
            self.aggregator.add_observation(obs.clone());
        }

        // Aggregate
        let aggregated = self.aggregator.aggregate(symbol)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Insufficient data for aggregation"))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("symbol", &aggregated.symbol).unwrap();
            dict.set_item("price_usd", aggregated.price_usd).unwrap();
            dict.set_item("mean_price_usd", aggregated.mean_price_usd).unwrap();
            dict.set_item("min_price_usd", aggregated.min_price_usd).unwrap();
            dict.set_item("max_price_usd", aggregated.max_price_usd).unwrap();
            dict.set_item("std_dev_usd", aggregated.std_dev_usd).unwrap();
            dict.set_item("source_count", aggregated.source_count).unwrap();
            dict.set_item("confidence", aggregated.confidence).unwrap();
            dict.set_item("aggregated_at", aggregated.aggregated_at.to_rfc3339()).unwrap();

            // Individual sources
            let sources: Vec<PyObject> = aggregated.observations.iter().map(|o| {
                let sdict = PyDict::new(py);
                sdict.set_item("source", o.source.to_string()).unwrap();
                sdict.set_item("price_usd", o.price_usd).unwrap();
                sdict.set_item("volume_24h_usd", o.volume_24h_usd).unwrap();
                sdict.set_item("change_24h_pct", o.change_24h_pct).unwrap();
                sdict.into()
            }).collect();
            dict.set_item("sources", sources).unwrap();

            Ok(dict.into())
        })
    }

    /// Detect price deviations across sources.
    ///
    /// Returns a list of deviations that exceed the threshold.
    fn detect_deviations(&self, symbol: &str) -> Vec<PyObject> {
        let deviations = self.aggregator.detect_deviations(symbol);
        Python::with_gil(|py| {
            deviations.iter().map(|d| {
                let dict = PyDict::new(py);
                dict.set_item("symbol", &d.symbol).unwrap();
                dict.set_item("source", d.source.to_string()).unwrap();
                dict.set_item("deviating_price_usd", d.deviating_price_usd).unwrap();
                dict.set_item("median_price_usd", d.median_price_usd).unwrap();
                dict.set_item("deviation_bps", d.deviation_bps).unwrap();
                dict.into()
            }).collect()
        })
    }

    /// Compute TWAP (Time-Weighted Average Price).
    ///
    /// Args:
    ///     symbol: Token symbol.
    ///     window_secs: Time window in seconds.
    ///
    /// Returns the TWAP or None if insufficient data.
    fn twap(&self, symbol: &str, window_secs: i64) -> Option<f64> {
        self.aggregator.twap(symbol, window_secs)
    }

    fn __repr__(&self) -> String {
        "PriceFeed".to_string()
    }
}
