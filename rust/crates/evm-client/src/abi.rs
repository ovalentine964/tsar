//! ABI encoding for DeFi protocols.
//!
//! Provides helpers for encoding calldata for Uniswap V3, 1inch, and Chainlink
//! contracts without requiring full `abigen!` macro expansion at compile time.

use alloy_primitives::{Address, U256 as AlloyU256};
use alloy_sol_types::{sol, SolCall};
use tracing::debug;

use crate::types::{EvmClientError, Protocol};

// ─── Uniswap V3 ABI ─────────────────────────────────────────────────

sol! {
    /// Uniswap V3 SwapRouter exactInputSingle call.
    #[derive(Debug, PartialEq)]
    interface ISwapRouter {
        function exactInputSingle(
            address tokenIn,
            address tokenOut,
            uint24 fee,
            address recipient,
            uint256 deadline,
            uint256 amountIn,
            uint256 amountOutMinimum,
            uint160 sqrtPriceLimitX96
        ) external payable returns (uint256 amountOut);
    }

    /// Uniswap V3 Quoter quoteExactInputSingle call.
    interface IQuoter {
        function quoteExactInputSingle(
            address tokenIn,
            address tokenOut,
            uint24 fee,
            uint256 amountIn,
            uint160 sqrtPriceLimitX96
        ) external returns (uint256 amountOut);
    }
}

// ─── Chainlink ABI ───────────────────────────────────────────────────

sol! {
    /// Chainlink Aggregator latestRoundData call.
    interface IChainlinkAggregator {
        function latestRoundData() external view returns (
            uint80 roundId,
            int256 answer,
            uint256 startedAt,
            uint256 updatedAt,
            uint80 answeredInRound
        );

        function decimals() external view returns (uint8);
    }
}

// ─── 1inch ABI (simplified) ─────────────────────────────────────────

sol! {
    /// 1inch Router swap call (simplified — actual 1inch uses complex encoded swap descriptions).
    interface IOneInchRouter {
        function swap(
            address executor,
            bytes desc,
            bytes permit,
            bytes data
        ) external payable returns (uint256, bytes);
    }
}

/// Encode a Uniswap V3 exactInputSingle swap call.
///
/// # Arguments
/// * `token_in` - Address of the input token
/// * `token_out` - Address of the output token
/// * `fee` - Pool fee tier (e.g., 3000 for 0.3%)
/// * `recipient` - Address to receive output tokens
/// * `deadline` - Unix timestamp deadline
/// * `amount_in` - Input amount in wei
/// * `amount_out_minimum` - Minimum acceptable output
/// * `sqrt_price_limit` - Price limit (0 for no limit)
pub fn encode_uniswap_v3_exact_input_single(
    token_in: &str,
    token_out: &str,
    fee: u32,
    recipient: &str,
    deadline: u64,
    amount_in: &str,
    amount_out_minimum: &str,
    sqrt_price_limit: &str,
) -> Result<Vec<u8>, EvmClientError> {
    let token_in_addr: Address = token_in
        .parse()
        .map_err(|_| EvmClientError::InvalidAddress(token_in.to_string()))?;
    let token_out_addr: Address = token_out
        .parse()
        .map_err(|_| EvmClientError::InvalidAddress(token_out.to_string()))?;
    let recipient_addr: Address = recipient
        .parse()
        .map_err(|_| EvmClientError::InvalidAddress(recipient.to_string()))?;

    let amount_in = AlloyU256::from_dec_str(amount_in)
        .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid amount_in: {e}")))?;
    let amount_out_min = AlloyU256::from_dec_str(amount_out_minimum)
        .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid amount_out_minimum: {e}")))?;
    let sqrt_price = AlloyU256::from_dec_str(sqrt_price_limit)
        .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid sqrt_price_limit: {e}")))?;

    let call = ISwapRouter::exactInputSingleCall {
        tokenIn: token_in_addr,
        tokenOut: token_out_addr,
        fee,
        recipient: recipient_addr,
        deadline: AlloyU256::from(deadline),
        amountIn: amount_in,
        amountOutMinimum: amount_out_min,
        sqrtPriceLimitX96: sqrt_price,
    };

    let encoded = call.abi_encode();
    debug!(protocol = "Uniswap V3", calldata_len = encoded.len(), "ABI encoded swap");

    Ok(encoded)
}

/// Encode a Uniswap V3 Quoter quoteExactInputSingle call.
pub fn encode_uniswap_v3_quote(
    token_in: &str,
    token_out: &str,
    fee: u32,
    amount_in: &str,
) -> Result<Vec<u8>, EvmClientError> {
    let token_in_addr: Address = token_in
        .parse()
        .map_err(|_| EvmClientError::InvalidAddress(token_in.to_string()))?;
    let token_out_addr: Address = token_out
        .parse()
        .map_err(|_| EvmClientError::InvalidAddress(token_out.to_string()))?;

    let amount_in = AlloyU256::from_dec_str(amount_in)
        .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid amount_in: {e}")))?;

    let call = IQuoter::quoteExactInputSingleCall {
        tokenIn: token_in_addr,
        tokenOut: token_out_addr,
        fee,
        amountIn: amount_in,
        sqrtPriceLimitX96: AlloyU256::ZERO,
    };

    let encoded = call.abi_encode();
    debug!(protocol = "Uniswap V3 Quoter", calldata_len = encoded.len(), "ABI encoded quote");

    Ok(encoded)
}

/// Encode a Chainlink Aggregator latestRoundData call.
pub fn encode_chainlink_latest_round_data() -> Vec<u8> {
    let call = IChainlinkAggregator::latestRoundDataCall {};
    call.abi_encode()
}

/// Encode a Chainlink Aggregator decimals call.
pub fn encode_chainlink_decimals() -> Vec<u8> {
    let call = IChainlinkAggregator::decimalsCall {};
    call.abi_encode()
}

/// Decode a Chainlink latestRoundData response.
///
/// Returns (round_id, answer, started_at, updated_at, answered_in_round).
pub fn decode_chainlink_round_data(
    data: &[u8],
) -> Result<(u64, i128, u64, u64, u64), EvmClientError> {
    use alloy_sol_types::SolValue;

    let decoded = <ISwapRouter::exactInputSingleCall as SolCall>::abi_decode(data, false);
    // Manual decode for the tuple return
    if data.len() < 160 {
        return Err(EvmClientError::AbiEncoding(
            "Insufficient data for Chainlink round".to_string(),
        ));
    }

    let round_id = u64::from_be_bytes(data[0..8].try_into().unwrap());
    let answer = i128::from_be_bytes(data[40..56].try_into().unwrap());
    let started_at = u64::from_be_bytes(data[88..96].try_into().unwrap());
    let updated_at = u64::from_be_bytes(data[120..128].try_into().unwrap());
    let answered_in_round = u64::from_be_bytes(data[152..160].try_into().unwrap());

    Ok((round_id, answer, started_at, updated_at, answered_in_round))
}

/// Encode calldata for a given protocol and parameters.
///
/// This is a convenience function that dispatches to the appropriate encoder.
pub fn encode_for_protocol(
    protocol: Protocol,
    params: &[String],
) -> Result<Vec<u8>, EvmClientError> {
    match protocol {
        Protocol::UniswapV3 => {
            if params.len() < 8 {
                return Err(EvmClientError::AbiEncoding(
                    "Uniswap V3 requires 8 parameters".to_string(),
                ));
            }
            encode_uniswap_v3_exact_input_single(
                &params[0], &params[1],
                params[2].parse().unwrap_or(3000),
                &params[3],
                params[4].parse().unwrap_or(0),
                &params[5], &params[6], &params[7],
            )
        }
        Protocol::Chainlink => Ok(encode_chainlink_latest_round_data()),
        Protocol::OneInch => {
            // 1inch swap encoding requires complex nested structures
            // Return placeholder — actual implementation needs full router ABI
            Err(EvmClientError::AbiEncoding(
                "1inch encoding requires full router ABI".to_string(),
            ))
        }
        _ => Err(EvmClientError::AbiEncoding(format!(
            "Unsupported protocol: {protocol}"
        ))),
    }
}
