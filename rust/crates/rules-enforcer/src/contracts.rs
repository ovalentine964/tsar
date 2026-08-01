//! Contract ABI bindings generated via ethers-rs abigen.

use ethers::prelude::abigen;

// Generate type-safe Rust bindings for each contract.
// These are generated at compile time from the Solidity ABI.

abigen!(
    TSARKillSwitch,
    r#"[
        function isActive() external view returns (bool)
        function isTradingAllowed() external view returns (bool)
        function getStatus() external view returns (bool active, string reason, uint256 activatedAt, int256 dailyPnl, uint8 circuitLevel, int256 drawdownBps)
        function updateDailyPnl(int256 dailyPnlBps) external
        function updateEquity(uint256 equity) external
        function emergencyHalt(string reason) external
        function checkPositionLimit(uint256 notionalBps, uint256 maxPositionBps) external view returns (bool)
        function dailyLossThresholdBps() external view returns (int256)
        function drawdownHaltThresholdBps() external view returns (int256)
        function drawdownFlattenThresholdBps() external view returns (int256)
        function circuitBreakerLevel() external view returns (uint8)
        function dailyPnlBps() external view returns (int256)
        function currentEquity() external view returns (uint256)
        function highWaterMark() external view returns (uint256)
        event KillSwitchActivated(string reason, uint256 timestamp, int256 dailyPnlBps, uint8 circuitBreakerLevel)
        event KillSwitchDeactivated(uint256 timestamp, address deactivator)
        event DailyPnlUpdated(int256 dailyPnlBps, uint256 timestamp, bool thresholdBreached)
        event EquityUpdated(uint256 equity, uint256 highWaterMark, int256 drawdownBps, uint8 circuitBreakerLevel)
        event CircuitBreakerChanged(uint8 oldLevel, uint8 newLevel, uint256 timestamp)
    ]"#
);

abigen!(
    TSARMandate,
    r#"[
        function currentRules() external view returns (bytes32[] allowedSymbols, uint256 maxPositionSizeBps, uint256 maxDailyTrades, uint256 maxLeverageBps, uint256 maxNotionalPerTrade, uint256 maxTotalExposureBps, bool allowMarketOrders, bool allowLimitOrders, bool allowStopOrders, bool allowShortSelling, uint256 minPaperTrades, uint256 minPaperDays, uint256 minWinRateBps)
        function getMandateVersion() external view returns (uint256 version, uint8 status)
        function checkOrder(bytes32 symbolHash, uint256 orderType, uint256 side, uint256 notionalBps, uint256 leverageBps, uint256 dailyTradeCount) external returns (bool allowed, string reason)
        function isSymbolAllowed(bytes32 symbolHash) external view returns (bool)
        function recordPaperTrade(bool isWin) external
        function getPaperTradingStatus() external view returns (uint256 trades, uint256 wins, uint256 winRateBps, uint256 daysInPaper)
        event OrderChecked(bytes32 symbolHash, uint256 orderType, bool allowed, string reason)
        event MandateCommitted(uint256 version, address committedBy, uint256 timestamp)
        event MandateRevoked(uint256 version, address revokedBy, uint256 timestamp)
        event MandateChangeExecuted(uint256 nonce, uint256 newVersion, uint256 timestamp)
    ]"#
);

abigen!(
    TSARAuditTrail,
    r#"[
        function logTrade(bytes32 symbolHash, uint8 side, uint256 notional, uint256 price, uint256 quantity, uint256 leverageBps, int256 realizedPnl, bytes32 orderId) external
        function logRuleCheck(bytes32 ruleId, bytes32 symbolHash, bool passed, string reason) external
        function logEnforcementAction(uint8 actionType, bytes32 ruleId, string details) external
        function logGovernanceChange(uint8 changeType, string description, bytes32 beforeHash, bytes32 afterHash) external
        function tradeCount() external view returns (uint256)
        function ruleCheckCount() external view returns (uint256)
        function enforcementCount() external view returns (uint256)
        function getDailySummary(uint256 epochDay) external view returns (uint256 trades, int256 pnl)
        function getSymbolSummary(bytes32 symbolHash) external view returns (uint256 trades, int256 pnl, uint256 latestTradeId)
        function getRecentTradeIds(uint256 count) external view returns (uint256[] tradeIds)
        event TradeLogged(uint256 indexed tradeId, bytes32 indexed symbolHash, uint8 side, uint256 notional, uint256 price, int256 realizedPnl, uint256 timestamp)
        event RuleCheckLogged(uint256 indexed checkId, bytes32 indexed ruleId, bytes32 indexed symbolHash, bool passed, string reason, uint256 timestamp)
        event EnforcementActionLogged(uint256 indexed actionId, uint8 actionType, bytes32 indexed ruleId, string details, uint256 timestamp)
    ]"#
);

abigen!(
    TSARGovernance,
    r#"[
        function propose(address target, bytes callData, uint8 opType, uint256 value, string description) external
        function confirm(uint256 proposalId) external
        function execute(uint256 proposalId) external
        function cancel(uint256 proposalId) external
        function emergencyPause() external
        function emergencyUnpause() external
        function isProposalReady(uint256 proposalId) external view returns (bool ready, bool timelockExpired)
        function getSigners() external view returns (address[5])
        function isSigner(address addr) external view returns (bool)
        function getProposal(uint256 proposalId) external view returns (address target, uint8 opType, string description, uint256 confirmations, bool executed, bool cancelled, uint256 proposedAt)
        function proposalCount() external view returns (uint256)
        function emergencyPaused() external view returns (bool)
        event ProposalCreated(uint256 indexed proposalId, address target, uint8 opType, string description, address proposer, uint256 timestamp)
        event ProposalConfirmed(uint256 indexed proposalId, address confirmer, uint256 confirmations, uint256 timestamp)
        event ProposalExecuted(uint256 indexed proposalId, address executor, uint256 timestamp)
        event EmergencyPaused(address indexed by, uint256 timestamp)
        event EmergencyUnpaused(address indexed by, uint256 timestamp)
    ]"#
);
