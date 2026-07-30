//! Safety net order generation.
//!
//! Generates stop-loss and take-profit order requests based on
//! entry price and percentage thresholds.

use tsar_core::types::OrderSide;

use crate::types::OrderRequest;

/// Safety net for generating protective orders.
pub struct SafetyNet;

impl SafetyNet {
    /// Generate a stop-loss order request.
    ///
    /// For a long position, the stop price is below entry.
    /// For a short position, the stop price is above entry.
    pub fn stop_loss(
        symbol: &str,
        side: OrderSide,
        qty: f64,
        entry: f64,
        pct: f64,
    ) -> OrderRequest {
        let sl_price = match side {
            OrderSide::Buy => entry * (1.0 - pct),
            OrderSide::Sell => entry * (1.0 + pct),
        };
        let sl_side = match side {
            OrderSide::Buy => OrderSide::Sell,
            OrderSide::Sell => OrderSide::Buy,
        };

        OrderRequest {
            id: uuid::Uuid::new_v4(),
            symbol: symbol.to_string(),
            side: sl_side,
            order_type: tsar_core::types::OrderType::StopLoss,
            quantity: qty,
            price: None,
            stop_price: Some(sl_price),
            time_in_force: crate::types::TimeInForce::Gtc,
            strategy: Some("safety_net".to_string()),
            signal_score: None,
            created_at: chrono::Utc::now(),
        }
    }

    /// Generate a take-profit order request.
    ///
    /// For a long position, the target price is above entry.
    /// For a short position, the target price is below entry.
    pub fn take_profit(
        symbol: &str,
        side: OrderSide,
        qty: f64,
        entry: f64,
        pct: f64,
    ) -> OrderRequest {
        let tp_price = match side {
            OrderSide::Buy => entry * (1.0 + pct),
            OrderSide::Sell => entry * (1.0 - pct),
        };
        let tp_side = match side {
            OrderSide::Buy => OrderSide::Sell,
            OrderSide::Sell => OrderSide::Buy,
        };

        OrderRequest {
            id: uuid::Uuid::new_v4(),
            symbol: symbol.to_string(),
            side: tp_side,
            order_type: tsar_core::types::OrderType::TakeProfit,
            quantity: qty,
            price: Some(tp_price),
            stop_price: None,
            time_in_force: crate::types::TimeInForce::Gtc,
            strategy: Some("safety_net".to_string()),
            signal_score: None,
            created_at: chrono::Utc::now(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stop_loss_long() {
        let sl = SafetyNet::stop_loss("BTC/USDT", OrderSide::Buy, 0.1, 50000.0, 0.02);
        assert_eq!(sl.side, OrderSide::Sell);
        assert_eq!(sl.stop_price, Some(49000.0));
        assert_eq!(sl.quantity, 0.1);
    }

    #[test]
    fn test_stop_loss_short() {
        let sl = SafetyNet::stop_loss("BTC/USDT", OrderSide::Sell, 0.1, 50000.0, 0.02);
        assert_eq!(sl.side, OrderSide::Buy);
        assert_eq!(sl.stop_price, Some(51000.0));
    }

    #[test]
    fn test_take_profit_long() {
        let tp = SafetyNet::take_profit("BTC/USDT", OrderSide::Buy, 0.1, 50000.0, 0.05);
        assert_eq!(tp.side, OrderSide::Sell);
        assert_eq!(tp.price, Some(52500.0));
    }

    #[test]
    fn test_take_profit_short() {
        let tp = SafetyNet::take_profit("BTC/USDT", OrderSide::Sell, 0.1, 50000.0, 0.05);
        assert_eq!(tp.side, OrderSide::Buy);
        assert_eq!(tp.price, Some(47500.0));
    }
}
