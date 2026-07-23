//! Integration tests for the order executor.
//!
//! Tests order placement, tracking, cancellation, and lifecycle management.

use tsar_order_executor::executor::OrderExecutor;
use tsar_order_executor::tracker::OrderTracker;
use tsar_order_executor::types::{OrderRequest, TimeInForce};
use tsar_core::types::{Order, OrderSide, OrderStatus, OrderType};

fn make_market_request(symbol: &str, side: OrderSide, qty: f64) -> OrderRequest {
    OrderRequest::market(symbol, side, qty)
}

fn make_limit_request(symbol: &str, side: OrderSide, qty: f64, price: f64) -> OrderRequest {
    OrderRequest::limit(symbol, side, qty, price)
}

// ── Order Executor ───────────────────────────────────────────────

#[test]
fn test_place_market_order() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut executor = OrderExecutor::new();
        let request = make_market_request("BTC/USDT", OrderSide::Buy, 0.1);

        let result = executor.place_order(&request).await.unwrap();

        assert_eq!(result.symbol, "BTC/USDT");
        assert_eq!(result.side, OrderSide::Buy);
        assert_eq!(result.order_type, OrderType::Market);
        assert_eq!(result.quantity, 0.1);
        assert_eq!(result.status, OrderStatus::Open);
        assert!(!result.exchange_order_id.is_empty());
    });
}

#[test]
fn test_place_limit_order() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut executor = OrderExecutor::new();
        let request = make_limit_request("ETH/USDT", OrderSide::Sell, 1.0, 3000.0);

        let result = executor.place_order(&request).await.unwrap();

        assert_eq!(result.symbol, "ETH/USDT");
        assert_eq!(result.side, OrderSide::Sell);
        assert_eq!(result.order_type, OrderType::Limit);
        assert_eq!(result.price, Some(3000.0));
        assert_eq!(result.status, OrderStatus::Open);
    });
}

#[test]
fn test_multiple_orders_tracked() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut executor = OrderExecutor::new();

        executor
            .place_order(&make_market_request("BTC/USDT", OrderSide::Buy, 0.1))
            .await
            .unwrap();
        executor
            .place_order(&make_market_request("ETH/USDT", OrderSide::Sell, 1.0))
            .await
            .unwrap();
        executor
            .place_order(&make_limit_request("SOL/USDT", OrderSide::Buy, 10.0, 100.0))
            .await
            .unwrap();

        assert_eq!(executor.tracker().len(), 3);
        assert_eq!(executor.get_open_orders(None).len(), 3);
        assert_eq!(executor.get_open_orders(Some("BTC/USDT")).len(), 1);
    });
}

#[test]
fn test_cancel_order_stub() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut executor = OrderExecutor::new();
        let request = make_market_request("BTC/USDT", OrderSide::Buy, 0.1);
        let result = executor.place_order(&request).await.unwrap();

        let cancelled = executor
            .cancel_order(&result.exchange_order_id, "BTC/USDT")
            .await
            .unwrap();
        assert!(cancelled);
    });
}

// ── Order Tracker ────────────────────────────────────────────────

fn sample_order() -> Order {
    Order {
        id: uuid::Uuid::new_v4(),
        exchange_order_id: Some("EX001".to_string()),
        symbol: "BTC/USDT".to_string(),
        side: OrderSide::Buy,
        order_type: OrderType::Limit,
        quantity: 0.5,
        price: Some(50000.0),
        stop_price: None,
        filled_quantity: 0.0,
        average_fill_price: None,
        status: OrderStatus::Open,
        created_at: chrono::Utc::now(),
        updated_at: chrono::Utc::now(),
    }
}

#[test]
fn test_tracker_lifecycle() {
    let mut tracker = OrderTracker::new();
    let order = sample_order();
    let id = order.id;
    let eid = order.exchange_order_id.clone().unwrap();

    tracker.track_order(order);
    assert_eq!(tracker.len(), 1);

    // Look up by internal ID
    let found = tracker.get_order(&id).unwrap();
    assert_eq!(found.symbol, "BTC/USDT");

    // Look up by exchange ID
    let found = tracker.get_by_exchange_id(&eid).unwrap();
    assert_eq!(found.id, id);

    // Update status
    tracker.update_status(&id, OrderStatus::Filled);
    assert_eq!(tracker.get_order(&id).unwrap().status, OrderStatus::Filled);

    // Remove
    tracker.remove_order(&id);
    assert!(tracker.is_empty());
}

#[test]
fn test_tracker_fill_updates() {
    let mut tracker = OrderTracker::new();
    let order = sample_order();
    let id = order.id;

    tracker.track_order(order);

    // Partial fill
    tracker.update_fill(&id, 0.25, 49990.0);
    let o = tracker.get_order(&id).unwrap();
    assert_eq!(o.status, OrderStatus::PartiallyFilled);
    assert_eq!(o.filled_quantity, 0.25);
    assert_eq!(o.average_fill_price, Some(49990.0));

    // Full fill
    tracker.update_fill(&id, 0.5, 49995.0);
    let o = tracker.get_order(&id).unwrap();
    assert_eq!(o.status, OrderStatus::Filled);
    assert_eq!(o.filled_quantity, 0.5);
}

#[test]
fn test_tracker_open_orders_filter() {
    let mut tracker = OrderTracker::new();

    let mut o1 = sample_order();
    o1.symbol = "BTC/USDT".to_string();
    let id1 = o1.id;
    tracker.track_order(o1);

    let mut o2 = sample_order();
    o2.symbol = "ETH/USDT".to_string();
    o2.status = OrderStatus::Filled;
    tracker.track_order(o2);

    let mut o3 = sample_order();
    o3.symbol = "BTC/USDT".to_string();
    tracker.track_order(o3);

    assert_eq!(tracker.get_open_orders(None).len(), 2); // o1, o3
    assert_eq!(tracker.get_open_orders(Some("BTC/USDT")).len(), 2);
    assert_eq!(tracker.get_open_orders(Some("ETH/USDT")).len(), 0);
}

#[test]
fn test_tracker_count_by_status() {
    let mut tracker = OrderTracker::new();

    let o1 = sample_order();
    tracker.track_order(o1);

    let mut o2 = sample_order();
    o2.status = OrderStatus::Filled;
    tracker.track_order(o2);

    let mut o3 = sample_order();
    o3.status = OrderStatus::Cancelled;
    tracker.track_order(o3);

    assert_eq!(tracker.count_by_status(OrderStatus::Open), 1);
    assert_eq!(tracker.count_by_status(OrderStatus::Filled), 1);
    assert_eq!(tracker.count_by_status(OrderStatus::Cancelled), 1);
}
