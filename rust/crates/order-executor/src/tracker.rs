//! Order status tracking and lifecycle management.
//!
//! Maintains a local registry of all orders and their current status,
//! enabling efficient status queries and fill tracking.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use tsar_core::types::{Order, OrderStatus};

/// Tracks the lifecycle of all orders placed by the executor.
#[derive(Debug)]
pub struct OrderTracker {
    /// All tracked orders by internal UUID.
    orders: HashMap<uuid::Uuid, Order>,
    /// Secondary index: exchange order ID → internal UUID.
    exchange_id_index: HashMap<String, uuid::Uuid>,
}

impl OrderTracker {
    /// Create a new empty order tracker.
    pub fn new() -> Self {
        Self {
            orders: HashMap::new(),
            exchange_id_index: HashMap::new(),
        }
    }

    /// Begin tracking an order.
    pub fn track_order(&mut self, order: Order) {
        if let Some(ref eid) = order.exchange_order_id {
            self.exchange_id_index.insert(eid.clone(), order.id);
        }
        self.orders.insert(order.id, order);
    }

    /// Update the status of an order by internal ID.
    pub fn update_status(
        &mut self,
        order_id: &uuid::Uuid,
        status: OrderStatus,
    ) -> Option<&Order> {
        if let Some(order) = self.orders.get_mut(order_id) {
            order.status = status;
            order.updated_at = Utc::now();
            tracing::debug!(
                order_id = %order_id,
                status = %status,
                "Order status updated"
            );
            Some(order)
        } else {
            None
        }
    }

    /// Update the filled quantity and average price for an order.
    pub fn update_fill(
        &mut self,
        order_id: &uuid::Uuid,
        filled_quantity: f64,
        average_price: f64,
    ) -> Option<&Order> {
        if let Some(order) = self.orders.get_mut(order_id) {
            order.filled_quantity = filled_quantity;
            order.average_fill_price = Some(average_price);
            order.updated_at = Utc::now();

            // Auto-update status based on fill
            if (filled_quantity - order.quantity).abs() < f64::EPSILON {
                order.status = OrderStatus::Filled;
            } else if filled_quantity > 0.0 {
                order.status = OrderStatus::PartiallyFilled;
            }

            Some(order)
        } else {
            None
        }
    }

    /// Look up an order by internal UUID.
    pub fn get_order(&self, order_id: &uuid::Uuid) -> Option<&Order> {
        self.orders.get(order_id)
    }

    /// Look up an order by exchange-assigned ID.
    pub fn get_by_exchange_id(&self, exchange_id: &str) -> Option<&Order> {
        self.exchange_id_index
            .get(exchange_id)
            .and_then(|id| self.orders.get(id))
    }

    /// Get all orders with status Open or PartiallyFilled.
    pub fn get_open_orders(&self, symbol: Option<&str>) -> Vec<&Order> {
        self.orders
            .values()
            .filter(|o| {
                matches!(o.status, OrderStatus::Open | OrderStatus::PartiallyFilled)
                    && symbol.map_or(true, |s| o.symbol == s)
            })
            .collect()
    }

    /// Get all orders regardless of status.
    pub fn get_all_orders(&self) -> Vec<&Order> {
        self.orders.values().collect()
    }

    /// Get count of orders by status.
    pub fn count_by_status(&self, status: OrderStatus) -> usize {
        self.orders.values().filter(|o| o.status == status).count()
    }

    /// Remove an order from tracking (e.g., after it's been fully processed and archived).
    pub fn remove_order(&mut self, order_id: &uuid::Uuid) -> Option<Order> {
        if let Some(order) = self.orders.remove(order_id) {
            if let Some(ref eid) = order.exchange_order_id {
                self.exchange_id_index.remove(eid);
            }
            Some(order)
        } else {
            None
        }
    }

    /// Total number of tracked orders.
    pub fn len(&self) -> usize {
        self.orders.len()
    }

    /// Returns true if no orders are being tracked.
    pub fn is_empty(&self) -> bool {
        self.orders.is_empty()
    }
}

impl Default for OrderTracker {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tsar_core::types::{OrderSide, OrderType};

    fn sample_order() -> Order {
        Order {
            id: uuid::Uuid::new_v4(),
            exchange_order_id: Some("EX123".to_string()),
            symbol: "BTC/USDT".to_string(),
            side: OrderSide::Buy,
            order_type: OrderType::Limit,
            quantity: 0.1,
            price: Some(50000.0),
            stop_price: None,
            filled_quantity: 0.0,
            average_fill_price: None,
            status: OrderStatus::Open,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn test_track_and_lookup() {
        let mut tracker = OrderTracker::new();
        let order = sample_order();
        let id = order.id;
        let eid = order.exchange_order_id.clone().unwrap();

        tracker.track_order(order);

        assert!(tracker.get_order(&id).is_some());
        assert!(tracker.get_by_exchange_id(&eid).is_some());
        assert_eq!(tracker.len(), 1);
    }

    #[test]
    fn test_update_status() {
        let mut tracker = OrderTracker::new();
        let order = sample_order();
        let id = order.id;

        tracker.track_order(order);
        tracker.update_status(&id, OrderStatus::Filled);

        assert_eq!(tracker.get_order(&id).unwrap().status, OrderStatus::Filled);
    }

    #[test]
    fn test_open_orders_filter() {
        let mut tracker = OrderTracker::new();

        let mut o1 = sample_order();
        o1.symbol = "BTC/USDT".to_string();
        tracker.track_order(o1);

        let mut o2 = sample_order();
        o2.symbol = "ETH/USDT".to_string();
        o2.status = OrderStatus::Filled;
        tracker.track_order(o2);

        assert_eq!(tracker.get_open_orders(None).len(), 1);
        assert_eq!(tracker.get_open_orders(Some("BTC/USDT")).len(), 1);
        assert_eq!(tracker.get_open_orders(Some("ETH/USDT")).len(), 0);
    }
}
