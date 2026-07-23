//! Auto-reconnection with exponential backoff.
//!
//! Manages reconnection logic for dropped WebSocket connections,
//! including configurable backoff policies and attempt limits.

use serde::{Deserialize, Serialize};

/// Reconnection policy configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReconnectPolicy {
    /// Maximum number of reconnection attempts before giving up.
    pub max_attempts: u32,
    /// Initial backoff delay in milliseconds.
    pub initial_delay_ms: u64,
    /// Maximum backoff delay in milliseconds.
    pub max_delay_ms: u64,
    /// Multiplier applied to delay after each failed attempt.
    pub backoff_multiplier: f64,
    /// Optional jitter factor (0.0–1.0) to add randomness to delay.
    pub jitter_factor: f64,
}

impl Default for ReconnectPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 10,
            initial_delay_ms: 1000,
            max_delay_ms: 30_000,
            backoff_multiplier: 2.0,
            jitter_factor: 0.1,
        }
    }
}

/// Tracks the state of a reconnection attempt sequence.
#[derive(Debug, Clone)]
pub struct ReconnectState {
    /// Current attempt number (0-indexed).
    pub attempt: u32,
    /// The policy governing this reconnection.
    pub policy: ReconnectPolicy,
    /// Whether reconnection is still possible.
    pub can_retry: bool,
}

impl ReconnectState {
    /// Create a new reconnection state with the given policy.
    pub fn new(policy: ReconnectPolicy) -> Self {
        Self {
            attempt: 0,
            can_retry: true,
            policy,
        }
    }

    /// Calculate the delay for the current attempt in milliseconds.
    ///
    /// Uses exponential backoff with optional jitter.
    pub fn next_delay_ms(&self) -> u64 {
        if self.attempt >= self.policy.max_attempts {
            return 0;
        }
        let base_delay = self.policy.initial_delay_ms as f64
            * self.policy.backoff_multiplier.powi(self.attempt as i32);
        let capped = base_delay.min(self.policy.max_delay_ms as f64);
        capped as u64
    }

    /// Record an attempt. Returns `false` if max attempts exceeded.
    pub fn record_attempt(&mut self) -> bool {
        self.attempt += 1;
        if self.attempt >= self.policy.max_attempts {
            self.can_retry = false;
            return false;
        }
        true
    }

    /// Reset the reconnection state for a fresh sequence.
    pub fn reset(&mut self) {
        self.attempt = 0;
        self.can_retry = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_policy() {
        let policy = ReconnectPolicy::default();
        assert_eq!(policy.max_attempts, 10);
        assert_eq!(policy.initial_delay_ms, 1000);
    }

    #[test]
    fn test_exponential_backoff() {
        let policy = ReconnectPolicy {
            max_attempts: 5,
            initial_delay_ms: 1000,
            max_delay_ms: 30_000,
            backoff_multiplier: 2.0,
            jitter_factor: 0.0,
        };
        let mut state = ReconnectState::new(policy);

        assert_eq!(state.next_delay_ms(), 1000); // attempt 0: 1s
        state.record_attempt();
        assert_eq!(state.next_delay_ms(), 2000); // attempt 1: 2s
        state.record_attempt();
        assert_eq!(state.next_delay_ms(), 4000); // attempt 2: 4s
        state.record_attempt();
        assert_eq!(state.next_delay_ms(), 8000); // attempt 3: 8s
    }

    #[test]
    fn test_max_attempts_exceeded() {
        let policy = ReconnectPolicy {
            max_attempts: 2,
            ..Default::default()
        };
        let mut state = ReconnectState::new(policy);

        assert!(state.record_attempt()); // attempt 1
        assert!(!state.record_attempt()); // attempt 2 — exhausted
        assert!(!state.can_retry);
    }
}
