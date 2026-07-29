use crate::types::OrderRequest;

pub struct SafetyNet;

impl SafetyNet {
    pub fn stop_loss(symbol: &str, side: &str, qty: f64, entry: f64, pct: f64) -> OrderRequest {
        let sl_price = if side == "buy" { entry * (1.0 - pct) } else { entry * (1.0 + pct) };
        let sl_side = if side == "buy" { "SELL" } else { "BUY" };
        OrderRequest {
            symbol: symbol.to_string(),
            side: sl_side.to_string(),
            order_type: "STOP_MARKET".to_string(),
            quantity: qty,
            price: None,
            stop_price: Some(sl_price),
            time_in_force: None,
        }
    }

    pub fn take_profit(symbol: &str, side: &str, qty: f64, entry: f64, pct: f64) -> OrderRequest {
        let tp_price = if side == "buy" { entry * (1.0 + pct) } else { entry * (1.0 - pct) };
        let tp_side = if side == "buy" { "SELL" } else { "BUY" };
        OrderRequest {
            symbol: symbol.to_string(),
            side: tp_side.to_string(),
            order_type: "LIMIT".to_string(),
            quantity: qty,
            price: Some(tp_price),
            stop_price: None,
            time_in_force: Some("GTC".to_string()),
        }
    }
}
