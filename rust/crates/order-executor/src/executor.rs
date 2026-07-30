//! Order placement and management.
//!
//! Handles the creation, placement, and cancellation of orders on exchanges.
//! Supports both paper trading (stub) and live trading (Binance REST API).

use tsar_core::error::{TsarError, TsarResult};
use tsar_core::types::{Order, OrderStatus};

use crate::client::{BinanceClient, BinanceConfig};
use crate::tracker::OrderTracker;
use crate::types::{Fill, OrderRequest, OrderResult, TimeInForce};

/// Execution mode for the order executor.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionMode {
    /// Paper trading — orders are simulated locally.
    Paper,
    /// Live trading — orders are sent to the exchange.
    Live,
}

/// Order execution engine.
///
/// Manages order lifecycle from request to completion.
/// Supports paper mode (simulated) and live mode (Binance REST API).
#[derive(Debug)]
pub struct OrderExecutor {
    /// Tracker for order state.
    tracker: OrderTracker,
    /// Execution mode.
    mode: ExecutionMode,
    /// Binance API client (only used in Live mode).
    client: Option<BinanceClient>,
    /// Paper mode: exchange order ID counter.
    next_paper_id: u64,
}

impl OrderExecutor {
    /// Create a new paper-trading order executor.
    pub fn new() -> Self {
        Self {
            tracker: OrderTracker::new(),
            mode: ExecutionMode::Paper,
            client: None,
            next_paper_id: 1,
        }
    }

    /// Create a live-trading order executor with Binance credentials.
    pub fn live(config: BinanceConfig) -> TsarResult<Self> {
        let client = BinanceClient::new(config)?;
        Ok(Self {
            tracker: OrderTracker::new(),
            mode: ExecutionMode::Live,
            client: Some(client),
            next_paper_id: 0,
        })
    }

    /// Get the current execution mode.
    pub fn mode(&self) -> ExecutionMode {
        self.mode
    }

    /// Place a new order.
    ///
    /// In Paper mode, simulates the order locally.
    /// In Live mode, sends to the Binance API.
    pub async fn place_order(&mut self, request: &OrderRequest) -> TsarResult<OrderResult> {
        match self.mode {
            ExecutionMode::Paper => self.place_paper_order(request).await,
            ExecutionMode::Live => self.place_live_order(request).await,
        }
    }

    /// Place a simulated paper order.
    async fn place_paper_order(&mut self, request: &OrderRequest) -> TsarResult<OrderResult> {
        let exchange_id = format!("PAPER-{}", self.next_paper_id);
        self.next_paper_id += 1;

        let now = chrono::Utc::now();
        let result = OrderResult {
            id: request.id,
            exchange_order_id: exchange_id.clone(),
            symbol: request.symbol.clone(),
            side: request.side,
            order_type: request.order_type,
            quantity: request.quantity,
            filled_quantity: 0.0,
            average_fill_price: None,
            price: request.price,
            status: OrderStatus::Open,
            fee: 0.0,
            fee_currency: None,
            placed_at: now,
            updated_at: now,
        };

        let order = Order {
            id: request.id,
            exchange_order_id: Some(exchange_id),
            symbol: request.symbol.clone(),
            side: request.side,
            order_type: request.order_type,
            quantity: request.quantity,
            price: request.price,
            stop_price: request.stop_price,
            filled_quantity: 0.0,
            average_fill_price: None,
            status: OrderStatus::Open,
            created_at: now,
            updated_at: now,
        };
        self.tracker.track_order(order);

        tracing::info!(
            order_id = %request.id,
            symbol = %request.symbol,
            side = %request.side,
            order_type = %request.order_type,
            quantity = request.quantity,
            "Paper order placed"
        );

        Ok(result)
    }

    /// Place a live order via the Binance API.
    async fn place_live_order(&mut self, request: &OrderRequest) -> TsarResult<OrderResult> {
        let client = self
            .client
            .as_ref()
            .ok_or_else(|| TsarError::OrderError("No API client configured".to_string()))?;

        // Convert symbol format: "BTC/USDT" → "BTCUSDT"
        let binance_symbol = request.symbol.replace('/', "");

        let order_type_str = match request.order_type {
            tsar_core::types::OrderType::Market => "MARKET",
            tsar_core::types::OrderType::Limit => "LIMIT",
            tsar_core::types::OrderType::StopLoss => "STOP_LOSS",
            tsar_core::types::OrderType::StopLimit => "STOP_LOSS_LIMIT",
            tsar_core::types::OrderType::TakeProfit => "TAKE_PROFIT",
        };

        let side_str = match request.side {
            tsar_core::types::OrderSide::Buy => "BUY",
            tsar_core::types::OrderSide::Sell => "SELL",
        };

        let tif = match request.time_in_force {
            TimeInForce::Gtc => Some("GTC"),
            TimeInForce::Ioc => Some("IOC"),
            TimeInForce::Fok => Some("FOK"),
            TimeInForce::Gtx => Some("GTX"),
        };

        let response = client
            .new_order(
                &binance_symbol,
                side_str,
                order_type_str,
                request.quantity,
                request.price,
                request.stop_price,
                tif,
            )
            .await?;

        let exchange_order_id = response
            .get("orderId")
            .and_then(|v| v.as_i64())
            .map(|id| id.to_string())
            .unwrap_or_default();

        let status_str = response
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("NEW");

        let filled_qty = response
            .get("executedQty")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);

        let avg_price = response
            .get("price")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok());

        let fee = response
            .get("fills")
            .and_then(|v| v.as_array())
            .map(|fills| {
                fills
                    .iter()
                    .filter_map(|f| {
                        let commission = f.get("commission")?.as_str()?.parse::<f64>().ok()?;
                        Some(commission)
                    })
                    .sum::<f64>()
            })
            .unwrap_or(0.0);

        let status = match status_str {
            "NEW" => OrderStatus::Open,
            "PARTIALLY_FILLED" => OrderStatus::PartiallyFilled,
            "FILLED" => OrderStatus::Filled,
            "CANCELED" => OrderStatus::Cancelled,
            "REJECTED" => OrderStatus::Rejected,
            "EXPIRED" => OrderStatus::Expired,
            _ => OrderStatus::Open,
        };

        let now = chrono::Utc::now();
        let result = OrderResult {
            id: request.id,
            exchange_order_id: exchange_order_id.clone(),
            symbol: request.symbol.clone(),
            side: request.side,
            order_type: request.order_type,
            quantity: request.quantity,
            filled_quantity: filled_qty,
            average_fill_price: avg_price,
            price: request.price,
            status,
            fee,
            fee_currency: Some("BNB".to_string()),
            placed_at: now,
            updated_at: now,
        };

        // Track the order
        let order = Order {
            id: request.id,
            exchange_order_id: Some(exchange_order_id),
            symbol: request.symbol.clone(),
            side: request.side,
            order_type: request.order_type,
            quantity: request.quantity,
            price: request.price,
            stop_price: request.stop_price,
            filled_quantity: filled_qty,
            average_fill_price: avg_price,
            status,
            created_at: now,
            updated_at: now,
        };
        self.tracker.track_order(order);

        tracing::info!(
            order_id = %request.id,
            exchange_id = %result.exchange_order_id,
            symbol = %request.symbol,
            side = %request.side,
            status = %status,
            filled_qty = filled_qty,
            "Live order placed"
        );

        Ok(result)
    }

    /// Cancel an order by its exchange order ID.
    pub async fn cancel_order(
        &mut self,
        order_id: &str,
        symbol: &str,
    ) -> TsarResult<bool> {
        match self.mode {
            ExecutionMode::Paper => {
                // Find and update the order in the tracker
                if let Some(order) = self.tracker.get_by_exchange_id(order_id) {
                    let id = order.id;
                    self.tracker.update_status(&id, OrderStatus::Cancelled);
                    tracing::info!(order_id = order_id, symbol = symbol, "Paper order cancelled");
                    Ok(true)
                } else {
                    Err(TsarError::OrderNotFound {
                        order_id: order_id.to_string(),
                    })
                }
            }
            ExecutionMode::Live => {
                let client = self
                    .client
                    .as_ref()
                    .ok_or_else(|| TsarError::OrderError("No API client configured".to_string()))?;

                let binance_symbol = symbol.replace('/', "");

                match client.cancel_order(&binance_symbol, order_id).await {
                    Ok(_) => {
                        // Update tracker
                        if let Some(order) = self.tracker.get_by_exchange_id(order_id) {
                            let id = order.id;
                            self.tracker.update_status(&id, OrderStatus::Cancelled);
                        }
                        tracing::info!(
                            order_id = order_id,
                            symbol = symbol,
                            "Live order cancelled"
                        );
                        Ok(true)
                    }
                    Err(e) => {
                        tracing::error!(
                            order_id = order_id,
                            error = %e,
                            "Failed to cancel live order"
                        );
                        Err(e)
                    }
                }
            }
        }
    }

    /// Get the status of an order.
    ///
    /// In Live mode, queries the exchange API.
    /// In Paper mode, returns the locally tracked status.
    pub async fn get_order_status(
        &self,
        order_id: &str,
        symbol: &str,
    ) -> TsarResult<Option<OrderResult>> {
        match self.mode {
            ExecutionMode::Paper => {
                // Look up in tracker
                if let Some(order) = self.tracker.get_by_exchange_id(order_id) {
                    Ok(Some(OrderResult {
                        id: order.id,
                        exchange_order_id: order
                            .exchange_order_id
                            .clone()
                            .unwrap_or_default(),
                        symbol: order.symbol.clone(),
                        side: order.side,
                        order_type: order.order_type,
                        quantity: order.quantity,
                        filled_quantity: order.filled_quantity,
                        average_fill_price: order.average_fill_price,
                        price: order.price,
                        status: order.status,
                        fee: 0.0,
                        fee_currency: None,
                        placed_at: order.created_at,
                        updated_at: order.updated_at,
                    }))
                } else {
                    Ok(None)
                }
            }
            ExecutionMode::Live => {
                let client = self
                    .client
                    .as_ref()
                    .ok_or_else(|| TsarError::OrderError("No API client configured".to_string()))?;

                let binance_symbol = symbol.replace('/', "");

                match client.query_order(&binance_symbol, order_id).await {
                    Ok(response) => {
                        let status_str = response
                            .get("status")
                            .and_then(|v| v.as_str())
                            .unwrap_or("UNKNOWN");

                        let status = match status_str {
                            "NEW" => OrderStatus::Open,
                            "PARTIALLY_FILLED" => OrderStatus::PartiallyFilled,
                            "FILLED" => OrderStatus::Filled,
                            "CANCELED" => OrderStatus::Cancelled,
                            "REJECTED" => OrderStatus::Rejected,
                            "EXPIRED" => OrderStatus::Expired,
                            _ => OrderStatus::Open,
                        };

                        let filled_qty = response
                            .get("executedQty")
                            .and_then(|v| v.as_str())
                            .and_then(|s| s.parse::<f64>().ok())
                            .unwrap_or(0.0);

                        // Update tracker
                        if let Some(order) = self.tracker.get_by_exchange_id(order_id) {
                            let id = order.id;
                            if filled_qty > 0.0 {
                                let avg_price = response
                                    .get("cummulativeQuoteQty")
                                    .and_then(|v| v.as_str())
                                    .and_then(|s| s.parse::<f64>().ok())
                                    .map(|quote_qty| {
                                        if filled_qty > 0.0 {
                                            quote_qty / filled_qty
                                        } else {
                                            0.0
                                        }
                                    })
                                    .unwrap_or(0.0);
                                self.tracker.update_fill(&id, filled_qty, avg_price);
                            }
                            self.tracker.update_status(&id, status);
                        }

                        Ok(None) // Caller should query tracker for full state
                    }
                    Err(e) => Err(e),
                }
            }
        }
    }

    /// Process a fill event from the WebSocket stream.
    ///
    /// Updates the tracker with fill information and returns
    /// the fill details if the order is tracked.
    pub fn process_fill(
        &mut self,
        exchange_order_id: &str,
        filled_qty: f64,
        fill_price: f64,
        fee: f64,
    ) -> Option<Fill> {
        let order = self.tracker.get_by_exchange_id(exchange_order_id)?;
        let order_id = order.id;
        let symbol = order.symbol.clone();

        // Update fill in tracker
        let existing_filled = order.filled_quantity;
        let new_total = existing_filled + filled_qty;

        // Calculate running average price
        let existing_pv = existing_filled * order.average_fill_price.unwrap_or(0.0);
        let new_pv = filled_qty * fill_price;
        let new_avg = if new_total > 0.0 {
            (existing_pv + new_pv) / new_total
        } else {
            fill_price
        };

        self.tracker.update_fill(&order_id, new_total, new_avg);

        tracing::info!(
            order_id = %order_id,
            exchange_id = exchange_order_id,
            filled_qty = filled_qty,
            fill_price = fill_price,
            total_filled = new_total,
            "Fill processed"
        );

        Some(Fill {
            id: uuid::Uuid::new_v4().to_string(),
            order_id: exchange_order_id.to_string(),
            symbol,
            price: fill_price,
            quantity: filled_qty,
            fee,
            fee_currency: "BNB".to_string(),
            is_maker: false,
            timestamp: chrono::Utc::now(),
        })
    }

    /// Get all open orders, optionally filtered by symbol.
    pub fn get_open_orders(&self, symbol: Option<&str>) -> Vec<&Order> {
        self.tracker.get_open_orders(symbol)
    }

    /// Get the order tracker reference.
    pub fn tracker(&self) -> &OrderTracker {
        &self.tracker
    }

    /// Get a mutable reference to the order tracker.
    pub fn tracker_mut(&mut self) -> &mut OrderTracker {
        &mut self.tracker
    }
}

impl Default for OrderExecutor {
    fn default() -> Self {
        Self::new()
    }
}
