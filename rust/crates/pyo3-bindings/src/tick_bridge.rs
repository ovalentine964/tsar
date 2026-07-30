//! PyO3 bridge for the tick processor.
//!
//! Exposes the OHLCV aggregator, spread calculator, ring buffer,
//! VWAP calculator, and tick stats to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use tsar_tick_processor::aggregator::{OhlcvAggregator, Timeframe};
use tsar_tick_processor::ring_buffer::RingBuffer;
use tsar_tick_processor::spread::SpreadCalculator;
use tsar_tick_processor::vwap::{TickStats, VwapCalculator};
use tsar_core::types::Tick;

/// Convert an OHLCV candle to a Python dict.
fn candle_to_dict(py: Python<'_>, c: &tsar_core::types::OHLCV) -> PyObject {
    let dict = PyDict::new(py);
    dict.set_item("symbol", &c.symbol).unwrap();
    dict.set_item("timeframe", &c.timeframe).unwrap();
    dict.set_item("open", c.open).unwrap();
    dict.set_item("high", c.high).unwrap();
    dict.set_item("low", c.low).unwrap();
    dict.set_item("close", c.close).unwrap();
    dict.set_item("volume", c.volume).unwrap();
    dict.set_item("timestamp", c.timestamp.to_rfc3339()).unwrap();
    dict.into()
}

/// Parse a timeframe string into a Timeframe enum.
fn parse_timeframe(s: &str) -> PyResult<Timeframe> {
    match s {
        "1s" => Ok(Timeframe::S1),
        "1m" => Ok(Timeframe::M1),
        "5m" => Ok(Timeframe::M5),
        "15m" => Ok(Timeframe::M15),
        "1h" => Ok(Timeframe::H1),
        "4h" => Ok(Timeframe::H4),
        "1d" | "1D" => Ok(Timeframe::D1),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Unknown timeframe: '{s}'. Supported: 1s, 1m, 5m, 15m, 1h, 4h, 1d"
        ))),
    }
}

/// Parse an ISO 8601 timestamp string.
fn parse_timestamp(s: &str) -> PyResult<chrono::DateTime<chrono::Utc>> {
    chrono::DateTime::parse_from_rfc3339(s)
        .or_else(|_| chrono::DateTime::parse_from_rfc3339(&(s.to_string() + "Z")))
        .map(|dt| dt.to_utc())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid timestamp: {e}")))
}

/// Python-visible OHLCV tick processor.
///
/// Aggregates raw ticks into OHLCV candles for multiple timeframes.
#[pyclass(name = "TickProcessor")]
pub struct PyTickProcessor {
    inner: OhlcvAggregator,
}

#[pymethods]
impl PyTickProcessor {
    /// Create a new tick processor with the given timeframe strings.
    ///
    /// Supported: "1s", "1m", "5m", "15m", "1h", "4h", "1d"
    #[new]
    #[pyo3(signature = (timeframes=None))]
    fn new(timeframes: Option<Vec<String>>) -> PyResult<Self> {
        let tfs = match timeframes {
            Some(tfs) => tfs
                .iter()
                .map(|s| parse_timeframe(s))
                .collect::<PyResult<Vec<_>>>()?,
            None => vec![Timeframe::M1, Timeframe::M5, Timeframe::M15, Timeframe::H1],
        };
        Ok(Self {
            inner: OhlcvAggregator::new(tfs),
        })
    }

    /// Feed a tick into the processor.
    ///
    /// Parameters:
    ///   - symbol: Trading pair (e.g., "BTC/USDT")
    ///   - price: Trade price
    ///   - amount: Trade quantity
    ///   - timestamp: ISO 8601 timestamp string
    ///
    /// Returns a list of completed candles as dicts.
    fn on_tick(
        &mut self,
        symbol: &str,
        price: f64,
        amount: f64,
        timestamp: &str,
    ) -> PyResult<Vec<PyObject>> {
        let ts = parse_timestamp(timestamp)?;

        let tick = Tick {
            symbol: symbol.to_string(),
            price,
            amount,
            side: tsar_core::types::OrderSide::Buy,
            timestamp: ts,
        };

        let completed = self.inner.on_tick(&tick);
        Python::with_gil(|py| {
            Ok(completed.iter().map(|c| candle_to_dict(py, c)).collect())
        })
    }

    /// Get the current (in-progress) candle for a symbol and timeframe.
    ///
    /// Returns None if no ticks have been received for this combination.
    fn current_candle(&self, symbol: &str, timeframe: &str) -> PyResult<Option<PyObject>> {
        let tf = parse_timeframe(timeframe)?;
        Python::with_gil(|py| {
            Ok(self
                .inner
                .current_candle(symbol, tf)
                .map(|c| candle_to_dict(py, &c)))
        })
    }

    /// Drain and return all completed candles since the last drain.
    fn drain_completed(&mut self) -> Vec<PyObject> {
        let completed = self.inner.drain_completed();
        Python::with_gil(|py| {
            completed.iter().map(|c| candle_to_dict(py, c)).collect()
        })
    }

    fn __repr__(&self) -> String {
        "TickProcessor".to_string()
    }
}

/// Python-visible spread calculator.
#[pyclass(name = "SpreadCalculator")]
pub struct PySpreadCalculator {
    inner: SpreadCalculator,
}

#[pymethods]
impl PySpreadCalculator {
    /// Create a new spread calculator for a symbol.
    #[new]
    #[pyo3(signature = (symbol, max_samples=1000))]
    fn new(symbol: &str, max_samples: usize) -> Self {
        Self {
            inner: SpreadCalculator::new(symbol, max_samples),
        }
    }

    /// Calculate spread from bid and ask prices.
    ///
    /// Returns a dict with spread details, or None if invalid.
    fn calculate(&mut self, bid: f64, ask: f64) -> PyResult<Option<PyObject>> {
        Ok(self.inner.calculate(bid, ask).map(|s| {
            Python::with_gil(|py| {
                let dict = PyDict::new(py);
                dict.set_item("symbol", &s.symbol).unwrap();
                dict.set_item("bid", s.bid).unwrap();
                dict.set_item("ask", s.ask).unwrap();
                dict.set_item("spread_abs", s.spread_abs).unwrap();
                dict.set_item("spread_bps", s.spread_bps).unwrap();
                dict.set_item("timestamp", s.timestamp.to_rfc3339())
                    .unwrap();
                dict.into()
            })
        }))
    }

    /// Get spread statistics from the rolling window.
    fn stats(&self) -> Option<PyObject> {
        self.inner.stats().map(|s| {
            Python::with_gil(|py| {
                let dict = PyDict::new(py);
                dict.set_item("symbol", &s.symbol).unwrap();
                dict.set_item("current_bps", s.current_bps).unwrap();
                dict.set_item("min_bps", s.min_bps).unwrap();
                dict.set_item("max_bps", s.max_bps).unwrap();
                dict.set_item("avg_bps", s.avg_bps).unwrap();
                dict.set_item("sample_count", s.sample_count).unwrap();
                dict.into()
            })
        })
    }

    /// Reset the calculator, clearing all samples.
    fn reset(&mut self) {
        self.inner.reset();
    }

    fn __repr__(&self) -> String {
        format!("SpreadCalculator(samples={})", self.inner.sample_count())
    }
}

/// Python-visible fixed-capacity ring buffer.
#[pyclass(name = "RingBuffer")]
pub struct PyRingBuffer {
    inner: RingBuffer<f64>,
}

#[pymethods]
impl PyRingBuffer {
    /// Create a new ring buffer with the given capacity.
    #[new]
    fn new(capacity: usize) -> Self {
        Self {
            inner: RingBuffer::new(capacity),
        }
    }

    /// Push a value into the buffer.
    fn push(&mut self, value: f64) {
        self.inner.push(value);
    }

    /// Return all values in order (oldest to newest) as a list.
    fn to_list(&self) -> Vec<f64> {
        self.inner.to_vec()
    }

    /// Get the most recently pushed value, or None if empty.
    fn latest(&self) -> Option<f64> {
        self.inner.latest().copied()
    }

    /// Get the number of elements in the buffer.
    fn __len__(&self) -> usize {
        self.inner.len()
    }

    /// Returns True if the buffer is empty.
    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Returns True if the buffer is at full capacity.
    fn is_full(&self) -> bool {
        self.inner.is_full()
    }

    /// The maximum capacity of the buffer.
    fn capacity(&self) -> usize {
        self.inner.capacity()
    }

    /// Clear all elements from the buffer.
    fn clear(&mut self) {
        self.inner.clear();
    }

    fn __repr__(&self) -> String {
        format!(
            "RingBuffer(len={}, capacity={})",
            self.inner.len(),
            self.inner.capacity()
        )
    }
}

/// Python-visible VWAP calculator.
///
/// Maintains a running VWAP from raw trade ticks.
#[pyclass(name = "VwapCalculator")]
pub struct PyVwapCalculator {
    inner: VwapCalculator,
}

#[pymethods]
impl PyVwapCalculator {
    /// Create a new VWAP calculator for a symbol.
    ///
    /// Optional `window_secs` for time-windowed VWAP (0 = session VWAP).
    #[new]
    #[pyo3(signature = (symbol, window_secs=0))]
    fn new(symbol: &str, window_secs: i64) -> Self {
        let inner = if window_secs > 0 {
            VwapCalculator::with_window(symbol, window_secs)
        } else {
            VwapCalculator::new(symbol)
        };
        Self { inner }
    }

    /// Feed a tick and return the updated VWAP.
    fn on_tick(&mut self, price: f64, volume: f64, timestamp: &str) -> PyResult<f64> {
        let ts = parse_timestamp(timestamp)?;
        let tick = Tick {
            symbol: self.inner.symbol.clone(),
            price,
            amount: volume,
            side: tsar_core::types::OrderSide::Buy,
            timestamp: ts,
        };
        Ok(self.inner.on_tick(&tick))
    }

    /// Get the current VWAP value.
    fn vwap(&self) -> f64 {
        self.inner.vwap()
    }

    /// Get the total volume accumulated.
    fn total_volume(&self) -> f64 {
        self.inner.total_volume()
    }

    /// Get the number of ticks processed.
    fn tick_count(&self) -> u64 {
        self.inner.tick_count()
    }

    /// Reset the calculator.
    fn reset(&mut self) {
        self.inner.reset();
    }

    fn __repr__(&self) -> String {
        format!(
            "VwapCalculator(symbol={}, vwap={:.2}, ticks={})",
            self.inner.symbol,
            self.inner.vwap(),
            self.inner.tick_count()
        )
    }
}

/// Python-visible tick-level statistics.
///
/// Tracks trade count, volume, price range, VWAP, and trade sizes.
#[pyclass(name = "TickStats")]
pub struct PyTickStats {
    inner: TickStats,
}

#[pymethods]
impl PyTickStats {
    /// Create new tick stats for a symbol.
    #[new]
    fn new(symbol: &str) -> Self {
        Self {
            inner: TickStats::new(symbol),
        }
    }

    /// Update stats with a new tick.
    fn on_tick(&mut self, price: f64, volume: f64, timestamp: &str) -> PyResult<()> {
        let ts = parse_timestamp(timestamp)?;
        let tick = Tick {
            symbol: self.inner.symbol.clone(),
            price,
            amount: volume,
            side: tsar_core::types::OrderSide::Buy,
            timestamp: ts,
        };
        self.inner.on_tick(&tick);
        Ok(())
    }

    /// Get all stats as a dict.
    fn stats(&self) -> PyObject {
        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("symbol", &self.inner.symbol).unwrap();
            dict.set_item("trade_count", self.inner.trade_count)
                .unwrap();
            dict.set_item("total_volume", self.inner.total_volume)
                .unwrap();
            dict.set_item("high", self.inner.high).unwrap();
            dict.set_item("low", self.inner.low).unwrap();
            dict.set_item("last_price", self.inner.last_price)
                .unwrap();
            dict.set_item("vwap", self.inner.vwap).unwrap();
            dict.set_item("open", self.inner.open).unwrap();
            dict.set_item("avg_trade_size", self.inner.avg_trade_size)
                .unwrap();
            dict.set_item("max_trade_size", self.inner.max_trade_size)
                .unwrap();
            dict.into()
        })
    }

    /// Reset all stats.
    fn reset(&mut self) {
        self.inner.reset();
    }

    fn __repr__(&self) -> String {
        format!(
            "TickStats(symbol={}, trades={}, volume={:.2})",
            self.inner.symbol, self.inner.trade_count, self.inner.total_volume
        )
    }
}
