//! Mempool scanner — real-time pending transaction monitoring.
//!
//! Connects to an Ethereum node's pending transaction stream via
//! WebSocket (newPendingTransactions) and filters for DEX swaps.
//!
//! Uses a bloom filter for O(1) address matching against known routers,
//! and a DashMap for concurrent access to pending swap state.

use std::collections::HashSet;
use std::sync::Arc;

use chrono::Utc;
use dashmap::DashMap;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

use crate::types::{KnownRouters, PendingSwap};

/// Configuration for the mempool scanner.
#[derive(Debug, Clone)]
pub struct MempoolConfig {
    /// Ethereum WebSocket RPC endpoint (e.g., wss://eth-mainnet.g.alchemy.com/v2/KEY).
    pub ws_rpc_url: String,
    /// HTTP RPC endpoint for transaction receipt queries.
    pub http_rpc_url: String,
    /// Maximum pending transactions to track simultaneously.
    pub max_pending: usize,
    /// Only track transactions interacting with these routers (empty = all known routers).
    pub target_routers: Vec<String>,
    /// Minimum swap value in USD to track (filters dust).
    pub min_swap_value_usd: f64,
}

impl Default for MempoolConfig {
    fn default() -> Self {
        Self {
            ws_rpc_url: String::new(),
            http_rpc_url: String::new(),
            max_pending: 10_000,
            target_routers: Vec::new(),
            min_swap_value_usd: 100.0,
        }
    }
}

/// A mempool scanner that monitors pending DEX swap transactions.
///
/// Spawns a background task that subscribes to `newPendingTransactions`
/// and filters for DEX router interactions. Detected swaps are sent
/// through an async channel for downstream processing.
pub struct MempoolScanner {
    config: MempoolConfig,
    /// Currently tracked pending swaps (tx_hash → PendingSwap).
    pending: Arc<DashMap<String, PendingSwap>>,
    /// Known router addresses for fast lookup.
    routers: HashSet<String>,
    /// Channel for sending detected swaps to consumers.
    tx_sender: Option<mpsc::UnboundedSender<PendingSwap>>,
    /// Handle to the background scanning task.
    scan_handle: Option<tokio::task::JoinHandle<()>>,
}

impl MempoolScanner {
    /// Create a new mempool scanner with the given configuration.
    pub fn new(config: MempoolConfig) -> Self {
        let routers: HashSet<String> = if config.target_routers.is_empty() {
            KnownRouters::all().iter().map(|s| s.to_string()).collect()
        } else {
            config.target_routers.iter().map(|s| s.to_lowercase()).collect()
        };

        Self {
            config,
            pending: Arc::new(DashMap::with_capacity(10_000)),
            routers,
            tx_sender: None,
            scan_handle: None,
        }
    }

    /// Start the mempool scanner.
    ///
    /// Returns a receiver that yields detected [`PendingSwap`] instances.
    /// The scanner runs as a background tokio task.
    pub fn start(&mut self) -> mpsc::UnboundedReceiver<PendingSwap> {
        let (tx, rx) = mpsc::unbounded_channel();
        self.tx_sender = Some(tx.clone());

        let pending = self.pending.clone();
        let routers = self.routers.clone();
        let config = self.config.clone();
        let max_pending = config.max_pending;

        let handle = tokio::spawn(async move {
            Self::scan_loop(config, pending, routers, tx, max_pending).await;
        });

        self.scan_handle = Some(handle);
        info!("Mempool scanner started");
        rx
    }

    /// Stop the mempool scanner.
    pub async fn stop(&mut self) {
        if let Some(handle) = self.scan_handle.take() {
            handle.abort();
            info!("Mempool scanner stopped");
        }
        self.tx_sender = None;
    }

    /// Get the current number of tracked pending swaps.
    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    /// Get a snapshot of all pending swaps.
    pub fn pending_swaps(&self) -> Vec<PendingSwap> {
        self.pending.iter().map(|entry| entry.value().clone()).collect()
    }

    /// Check if a specific transaction is being tracked.
    pub fn has_tx(&self, tx_hash: &str) -> bool {
        self.pending.contains_key(tx_hash)
    }

    /// Remove a transaction from tracking (e.g., after it's confirmed).
    pub fn remove_tx(&self, tx_hash: &str) -> Option<PendingSwap> {
        self.pending.remove(tx_hash).map(|(_, v)| v)
    }

    /// Background scan loop — connects to WebSocket and processes pending txs.
    async fn scan_loop(
        config: MempoolConfig,
        pending: Arc<DashMap<String, PendingSwap>>,
        routers: HashSet<String>,
        tx: mpsc::UnboundedSender<PendingSwap>,
        max_pending: usize,
    ) {
        use futures_util::{SinkExt, StreamExt};
        use tokio_tungstenite::connect_async;
        use tokio_tungstenite::tungstenite::Message;

        info!(rpc_url = %config.ws_rpc_url, "Connecting to mempool stream");

        let (ws_stream, _) = match connect_async(&config.ws_rpc_url).await {
            Ok(pair) => pair,
            Err(e) => {
                warn!(error = %e, "Failed to connect to mempool WebSocket");
                return;
            }
        };

        let (mut write, mut read) = ws_stream.split();

        // Subscribe to pending transactions
        let subscribe_msg = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newPendingTransactions", true]
        });

        if let Err(e) = write
            .send(Message::Text(subscribe_msg.to_string().into()))
            .await
        {
            warn!(error = %e, "Failed to subscribe to pending transactions");
            return;
        }

        info!("Subscribed to newPendingTransactions stream");

        while let Some(msg_result) = read.next().await {
            match msg_result {
                Ok(Message::Text(text)) => {
                    Self::process_message(
                        &text,
                        &pending,
                        &routers,
                        &tx,
                        max_pending,
                    )
                    .await;
                }
                Ok(Message::Ping(data)) => {
                    let _ = write.send(Message::Pong(data)).await;
                }
                Ok(Message::Close(_)) => {
                    warn!("Mempool WebSocket closed by remote");
                    break;
                }
                Err(e) => {
                    warn!(error = %e, "Mempool WebSocket error");
                    break;
                }
                _ => {}
            }
        }

        info!("Mempool scan loop exited");
    }

    /// Process a single WebSocket message containing a pending transaction.
    async fn process_message(
        raw: &str,
        pending: &Arc<DashMap<String, PendingSwap>>,
        routers: &HashSet<String>,
        tx: &mpsc::UnboundedSender<PendingSwap>,
        max_pending: usize,
    ) {
        let value: serde_json::Value = match serde_json::from_str(raw) {
            Ok(v) => v,
            Err(_) => return,
        };

        // Extract transaction from subscription result
        let tx_obj = match value.get("params").and_then(|p| p.get("result")) {
            Some(obj) => obj,
            None => return,
        };

        let to_addr = match tx_obj.get("to").and_then(|v| v.as_str()) {
            Some(addr) => addr.to_lowercase(),
            None => return, // Contract creation, skip
        };

        // Fast check: is this going to a known DEX router?
        if !routers.contains(&to_addr) {
            return;
        }

        let tx_hash = match tx_obj.get("hash").and_then(|v| v.as_str()) {
            Some(h) => h.to_string(),
            None => return,
        };

        let from = tx_obj
            .get("from")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();

        let gas_price = tx_obj
            .get("gasPrice")
            .and_then(|v| v.as_str())
            .and_then(|s| u128::from_str_radix(s.trim_start_matches("0x"), 16).ok())
            .map(|gp| gp as f64 / 1e9) // Convert wei to gwei
            .unwrap_or(0.0);

        let max_priority_fee = tx_obj
            .get("maxPriorityFeePerGas")
            .and_then(|v| v.as_str())
            .and_then(|s| u128::from_str_radix(s.trim_start_matches("0x"), 16).ok())
            .map(|fee| fee as f64 / 1e9);

        let input_data = tx_obj
            .get("input")
            .and_then(|v| v.as_str())
            .unwrap_or("0x");

        // Decode swap parameters from calldata (simplified)
        let (token_in, token_out, amount_in, amount_out_min) =
            Self::decode_swap_calldata(input_data, &to_addr);

        let swap = PendingSwap {
            tx_hash: tx_hash.clone(),
            from,
            router: to_addr,
            token_in,
            token_out,
            amount_in,
            amount_out_min,
            gas_price_gwei: gas_price,
            max_priority_fee_gwei: max_priority_fee,
            block_number: 0, // Will be filled when confirmed
            timestamp: Utc::now(),
            slippage_pct: if amount_in > 0.0 && amount_out_min > 0.0 {
                // Simplified slippage estimate
                0.5
            } else {
                0.0
            },
        };

        // Evict old entries if at capacity
        if pending.len() >= max_pending {
            // Remove oldest 10% of entries
            let cutoff = Utc::now() - chrono::Duration::seconds(30);
            pending.retain(|_, v| v.timestamp > cutoff);
        }

        pending.insert(tx_hash, swap.clone());
        debug!(
            tx_hash = %swap.tx_hash,
            router = %swap.router,
            amount_in = swap.amount_in,
            "Pending DEX swap detected"
        );

        let _ = tx.send(swap);
    }

    /// Decode swap calldata (simplified — production should use full ABI decoding).
    ///
    /// Returns (token_in, token_out, amount_in, amount_out_min).
    fn decode_swap_calldata(
        input: &str,
        router: &str,
    ) -> (String, String, f64, f64) {
        // Simplified: extract function selector and basic params
        // Production: use alloy-sol-types for full ABI decoding
        if input.len() < 10 {
            return (
                String::new(),
                String::new(),
                0.0,
                0.0,
            );
        }

        let selector = &input[..10];

        // Common Uniswap V2 router function selectors
        match selector {
            // swapExactTokensForTokens(uint256,uint256,address[],address,uint256)
            "0x38ed1739" | "0x8803dbee" => {
                // Decode amountIn (first uint256 param)
                let amount_in = if input.len() >= 74 {
                    u128::from_str_radix(&input[10..74], 16)
                        .map(|v| v as f64 / 1e18)
                        .unwrap_or(0.0)
                } else {
                    0.0
                };
                (
                    "UNKNOWN".to_string(),
                    "UNKNOWN".to_string(),
                    amount_in,
                    0.0,
                )
            }
            // swapExactETHForTokens(uint256,address[],address,uint256)
            "0x7ff36ab5" => {
                (
                    "ETH".to_string(),
                    "UNKNOWN".to_string(),
                    0.0,
                    0.0,
                )
            }
            // swapExactTokensForETH(uint256,uint256,address[],address,uint256)
            "0x18cbafe5" => {
                (
                    "UNKNOWN".to_string(),
                    "ETH".to_string(),
                    0.0,
                    0.0,
                )
            }
            _ => {
                (
                    "UNKNOWN".to_string(),
                    "UNKNOWN".to_string(),
                    0.0,
                    0.0,
                )
            }
        }
    }
}
