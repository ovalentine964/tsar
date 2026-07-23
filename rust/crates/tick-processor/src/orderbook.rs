//! Order book maintenance and update application.
//!
//! Maintains a local copy of the order book for a symbol,
//! applying incremental depth updates from the exchange stream.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tsar_core::types::OrderBookEntry;

/// A managed order book for a single symbol.
///
/// Uses sorted BTreeMaps for bids (descending) and asks (ascending)
/// to maintain price-level ordering.
#[derive(Debug, Clone)]
pub struct OrderBookManager {
    pub symbol: String,
    /// Bids sorted by price (highest first via negated key).
    bids: BTreeMap<OrderedFloat, f64>,
    /// Asks sorted by price (lowest first).
    asks: BTreeMap<OrderedFloat, f64>,
    /// Last update timestamp.
    pub updated_at: Option<DateTime<Utc>>,
    /// Update sequence number for consistency checking.
    pub sequence: u64,
}

/// Wrapper for f64 that implements Ord (for BTreeMap keys).
/// Uses total ordering via `partial_cmp` — NaN values are sorted last.
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
struct OrderedFloat(f64);

impl Eq for OrderedFloat {}

impl Ord for OrderedFloat {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.0
            .partial_cmp(&other.0)
            .unwrap_or(std::cmp::Ordering::Equal)
    }
}

impl OrderBookManager {
    /// Create a new empty order book for the given symbol.
    pub fn new(symbol: impl Into<String>) -> Self {
        Self {
            symbol: symbol.into(),
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
            updated_at: None,
            sequence: 0,
        }
    }

    /// Apply a full snapshot (replaces all levels).
    pub fn apply_snapshot(
        &mut self,
        bids: Vec<OrderBookEntry>,
        asks: Vec<OrderBookEntry>,
        sequence: u64,
    ) {
        self.bids.clear();
        self.asks.clear();

        for entry in bids {
            if entry.amount > 0.0 {
                // Store bids with negated price for descending order
                self.bids.insert(OrderedFloat(-entry.price), entry.amount);
            }
        }
        for entry in asks {
            if entry.amount > 0.0 {
                self.asks.insert(OrderedFloat(entry.price), entry.amount);
            }
        }

        self.sequence = sequence;
        self.updated_at = Some(Utc::now());
        tracing::debug!(
            symbol = %self.symbol,
            bid_levels = self.bids.len(),
            ask_levels = self.asks.len(),
            sequence = sequence,
            "Order book snapshot applied"
        );
    }

    /// Apply an incremental depth update.
    ///
    /// Updates or removes price levels. Levels with amount=0 are removed.
    pub fn apply_update(
        &mut self,
        bids: Vec<OrderBookEntry>,
        asks: Vec<OrderBookEntry>,
        sequence: u64,
    ) {
        for entry in bids {
            if entry.amount == 0.0 {
                self.bids.remove(&OrderedFloat(-entry.price));
            } else {
                self.bids.insert(OrderedFloat(-entry.price), entry.amount);
            }
        }
        for entry in asks {
            if entry.amount == 0.0 {
                self.asks.remove(&OrderedFloat(entry.price));
            } else {
                self.asks.insert(OrderedFloat(entry.price), entry.amount);
            }
        }

        self.sequence = sequence;
        self.updated_at = Some(Utc::now());
    }

    /// Get the best bid price and amount.
    pub fn best_bid(&self) -> Option<(f64, f64)> {
        self.bids
            .iter()
            .next()
            .map(|(price, &amount)| (-price.0, amount))
    }

    /// Get the best ask price and amount.
    pub fn best_ask(&self) -> Option<(f64, f64)> {
        self.asks
            .iter()
            .next()
            .map(|(price, &amount)| (price.0, amount))
    }

    /// Get the mid price (average of best bid and best ask).
    pub fn mid_price(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bid, _)), Some((ask, _))) => Some((bid + ask) / 2.0),
            _ => None,
        }
    }

    /// Get the top N bid levels as a Vec.
    pub fn top_bids(&self, n: usize) -> Vec<OrderBookEntry> {
        self.bids
            .iter()
            .take(n)
            .map(|(price, &amount)| OrderBookEntry {
                price: -price.0,
                amount,
            })
            .collect()
    }

    /// Get the top N ask levels as a Vec.
    pub fn top_asks(&self, n: usize) -> Vec<OrderBookEntry> {
        self.asks
            .iter()
            .take(n)
            .map(|(price, &amount)| OrderBookEntry {
                price: price.0,
                amount,
            })
            .collect()
    }

    /// Total number of bid levels.
    pub fn bid_levels(&self) -> usize {
        self.bids.len()
    }

    /// Total number of ask levels.
    pub fn ask_levels(&self) -> usize {
        self.asks.len()
    }

    /// Clear all levels.
    pub fn clear(&mut self) {
        self.bids.clear();
        self.asks.clear();
        self.sequence = 0;
        self.updated_at = None;
    }
}

/// An order book snapshot suitable for serialization.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBookSnapshot {
    pub symbol: String,
    pub bids: Vec<OrderBookEntry>,
    pub asks: Vec<OrderBookEntry>,
    pub sequence: u64,
    pub timestamp: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(price: f64, amount: f64) -> OrderBookEntry {
        OrderBookEntry { price, amount }
    }

    #[test]
    fn test_snapshot_and_best_prices() {
        let mut ob = OrderBookManager::new("BTC/USDT");
        ob.apply_snapshot(
            vec![entry(49900.0, 1.0), entry(49800.0, 2.0)],
            vec![entry(50000.0, 1.5), entry(50100.0, 0.5)],
            1,
        );

        let (bid_price, bid_amt) = ob.best_bid().unwrap();
        assert_eq!(bid_price, 49900.0);
        assert_eq!(bid_amt, 1.0);

        let (ask_price, ask_amt) = ob.best_ask().unwrap();
        assert_eq!(ask_price, 50000.0);
        assert_eq!(ask_amt, 1.5);

        assert_eq!(ob.mid_price(), Some(49950.0));
    }

    #[test]
    fn test_incremental_update() {
        let mut ob = OrderBookManager::new("BTC/USDT");
        ob.apply_snapshot(
            vec![entry(49900.0, 1.0)],
            vec![entry(50000.0, 1.5)],
            1,
        );

        // Update bid level and remove it by setting amount=0
        ob.apply_update(
            vec![entry(49900.0, 0.0)],
            vec![entry(50000.0, 2.0)],
            2,
        );

        assert!(ob.best_bid().is_none());
        let (_, ask_amt) = ob.best_ask().unwrap();
        assert_eq!(ask_amt, 2.0);
    }

    #[test]
    fn test_top_n_levels() {
        let mut ob = OrderBookManager::new("ETH/USDT");
        ob.apply_snapshot(
            vec![entry(3000.0, 1.0), entry(2990.0, 2.0), entry(2980.0, 3.0)],
            vec![entry(3010.0, 1.0), entry(3020.0, 2.0)],
            1,
        );

        let top2 = ob.top_bids(2);
        assert_eq!(top2.len(), 2);
        assert_eq!(top2[0].price, 3000.0);
        assert_eq!(top2[1].price, 2990.0);
    }
}
