// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TSARAuditTrail
 * @notice On-chain audit trail for all trades and rule enforcement actions.
 * @dev Every trade, rule check, and enforcement action is logged immutably.
 *
 * PURPOSE:
 *   Provide a tamper-proof, publicly verifiable record of:
 *   - Every trade executed (symbol, size, price, P&L)
 *   - Every rule check performed (pass/fail, which rule)
 *   - Every enforcement action (kill switch, mandate block)
 *   - Every governance change (mandate updates, threshold changes)
 *
 * INTEGRATION WITH TSAR:
 *   - Rust bridge calls logTrade() after each execution
 *   - Rust bridge calls logRuleCheck() for every pre-trade check
 *   - Python AuditLogger reads events for compliance reports
 *   - External auditors can verify all activity on-chain
 */

import "@openzeppelin/contracts/access/AccessControl.sol";

contract TSARAuditTrail is AccessControl {
    // ═══════════════════════════════════════════════════════════
    // ROLES
    // ═══════════════════════════════════════════════════════════

    bytes32 public constant LOGGER_ROLE = keccak256("LOGGER_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");

    // ═══════════════════════════════════════════════════════════
    // TYPES
    // ═══════════════════════════════════════════════════════════

    /// @notice Trade record stored on-chain
    struct TradeRecord {
        uint256 tradeId;
        bytes32 symbolHash;
        uint8 side;             // 0=BUY, 1=SELL
        uint256 notional;       // in wei
        uint256 price;          // scaled price (18 decimals)
        uint256 quantity;       // base asset quantity (18 decimals)
        uint256 leverageBps;    // leverage in basis points
        int256 realizedPnl;     // realized P&L in wei
        uint256 timestamp;
        address executor;       // which address executed
        bytes32 orderId;        // exchange order ID hash
    }

    /// @notice Rule check record
    struct RuleCheckRecord {
        uint256 checkId;
        bytes32 ruleId;         // which rule was checked
        bytes32 symbolHash;
        bool passed;
        string reason;
        uint256 timestamp;
        address checker;
    }

    /// @notice Enforcement action record
    struct EnforcementRecord {
        uint256 actionId;
        uint8 actionType;       // 0=KILL_SWITCH, 1=MANDATE_BLOCK, 2=POSITION_LIMIT, 3=LEVERAGE_BLOCK
        bytes32 ruleId;
        string details;
        uint256 timestamp;
        address actor;
    }

    /// @notice Governance change record
    struct GovernanceRecord {
        uint256 changeId;
        uint8 changeType;       // 0=MANDATE_UPDATE, 1=THRESHOLD_CHANGE, 2=ROLE_CHANGE, 3=PARAMETER_CHANGE
        string description;
        bytes32 beforeHash;     // hash of previous state
        bytes32 afterHash;      // hash of new state
        uint256 timestamp;
        address actor;
    }

    // ═══════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════

    /// @notice Trade counter (also serves as trade ID)
    uint256 public tradeCount;

    /// @notice Rule check counter
    uint256 public ruleCheckCount;

    /// @notice Enforcement action counter
    uint256 public enforcementCount;

    /// @notice Governance change counter
    uint256 public governanceChangeCount;

    /// @notice All trade records (tradeId => TradeRecord)
    mapping(uint256 => TradeRecord) public trades;

    /// @notice All rule check records
    mapping(uint256 => RuleCheckRecord) public ruleChecks;

    /// @notice All enforcement records
    mapping(uint256 => EnforcementRecord) public enforcementActions;

    /// @notice All governance records
    mapping(uint256 => GovernanceRecord) public governanceChanges;

    /// @notice Daily trade count (epoch day => count)
    mapping(uint256 => uint256) public dailyTradeCount;

    /// @notice Daily P&L tracking (epoch day => P&L in wei)
    mapping(uint256 => int256) public dailyPnl;

    /// @notice Symbol trade count (symbolHash => count)
    mapping(bytes32 => uint256) public symbolTradeCount;

    /// @notice Cumulative P&L by symbol (symbolHash => P&L in wei)
    mapping(bytes32 => int256) public symbolPnl;

    /// @notice Latest trade ID per symbol for quick lookup
    mapping(bytes32 => uint256) public latestTradeBySymbol;

    // ═══════════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════════

    event TradeLogged(
        uint256 indexed tradeId,
        bytes32 indexed symbolHash,
        uint8 side,
        uint256 notional,
        uint256 price,
        int256 realizedPnl,
        uint256 timestamp
    );

    event RuleCheckLogged(
        uint256 indexed checkId,
        bytes32 indexed ruleId,
        bytes32 indexed symbolHash,
        bool passed,
        string reason,
        uint256 timestamp
    );

    event EnforcementActionLogged(
        uint256 indexed actionId,
        uint8 actionType,
        bytes32 indexed ruleId,
        string details,
        uint256 timestamp
    );

    event GovernanceChangeLogged(
        uint256 indexed changeId,
        uint8 changeType,
        string description,
        uint256 timestamp
    );

    // ═══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════════════════════

    constructor(address _admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(LOGGER_ROLE, _admin);
        _grantRole(AUDITOR_ROLE, _admin);
    }

    // ═══════════════════════════════════════════════════════════
    // TRADE LOGGING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Log a trade execution on-chain.
     * @dev Called by Rust bridge after each trade settlement.
     * @param _symbolHash Hash of the trading pair
     * @param _side 0=BUY, 1=SELL
     * @param _notional Trade notional value in wei
     * @param _price Execution price (18 decimals)
     * @param _quantity Base asset quantity (18 decimals)
     * @param _leverageBps Leverage used in basis points
     * @param _realizedPnl Realized P&L in wei (negative = loss)
     * @param _orderId Exchange order ID hash
     */
    function logTrade(
        bytes32 _symbolHash,
        uint8 _side,
        uint256 _notional,
        uint256 _price,
        uint256 _quantity,
        uint256 _leverageBps,
        int256 _realizedPnl,
        bytes32 _orderId
    ) external onlyRole(LOGGER_ROLE) {
        tradeCount++;

        uint256 epochDay = block.timestamp / 1 days;

        trades[tradeCount] = TradeRecord({
            tradeId: tradeCount,
            symbolHash: _symbolHash,
            side: _side,
            notional: _notional,
            price: _price,
            quantity: _quantity,
            leverageBps: _leverageBps,
            realizedPnl: _realizedPnl,
            timestamp: block.timestamp,
            executor: msg.sender,
            orderId: _orderId
        });

        // Update aggregations
        dailyTradeCount[epochDay]++;
        dailyPnl[epochDay] += _realizedPnl;
        symbolTradeCount[_symbolHash]++;
        symbolPnl[_symbolHash] += _realizedPnl;
        latestTradeBySymbol[_symbolHash] = tradeCount;

        emit TradeLogged(
            tradeCount,
            _symbolHash,
            _side,
            _notional,
            _price,
            _realizedPnl,
            block.timestamp
        );
    }

    // ═══════════════════════════════════════════════════════════
    // RULE CHECK LOGGING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Log a rule check result on-chain.
     * @dev Called by Rust bridge for every pre-trade validation.
     * @param _ruleId Identifier for the rule checked
     * @param _symbolHash Symbol being checked
     * @param _passed Whether the check passed
     * @param _reason Human-readable reason
     */
    function logRuleCheck(
        bytes32 _ruleId,
        bytes32 _symbolHash,
        bool _passed,
        string calldata _reason
    ) external onlyRole(LOGGER_ROLE) {
        ruleCheckCount++;

        ruleChecks[ruleCheckCount] = RuleCheckRecord({
            checkId: ruleCheckCount,
            ruleId: _ruleId,
            symbolHash: _symbolHash,
            passed: _passed,
            reason: _reason,
            timestamp: block.timestamp,
            checker: msg.sender
        });

        emit RuleCheckLogged(
            ruleCheckCount,
            _ruleId,
            _symbolHash,
            _passed,
            _reason,
            block.timestamp
        );
    }

    // ═══════════════════════════════════════════════════════════
    // ENFORCEMENT LOGGING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Log an enforcement action on-chain.
     * @dev Called when kill switch activates, mandate blocks a trade, etc.
     * @param _actionType Type of enforcement action
     * @param _ruleId The rule that triggered enforcement
     * @param _details Human-readable details
     */
    function logEnforcementAction(
        uint8 _actionType,
        bytes32 _ruleId,
        string calldata _details
    ) external onlyRole(LOGGER_ROLE) {
        enforcementCount++;

        enforcementActions[enforcementCount] = EnforcementRecord({
            actionId: enforcementCount,
            actionType: _actionType,
            ruleId: _ruleId,
            details: _details,
            timestamp: block.timestamp,
            actor: msg.sender
        });

        emit EnforcementActionLogged(
            enforcementCount,
            _actionType,
            _ruleId,
            _details,
            block.timestamp
        );
    }

    // ═══════════════════════════════════════════════════════════
    // GOVERNANCE LOGGING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Log a governance change on-chain.
     * @param _changeType Type of governance change
     * @param _description What changed
     * @param _beforeHash Hash of state before change
     * @param _afterHash Hash of state after change
     */
    function logGovernanceChange(
        uint8 _changeType,
        string calldata _description,
        bytes32 _beforeHash,
        bytes32 _afterHash
    ) external onlyRole(LOGGER_ROLE) {
        governanceChangeCount++;

        governanceChanges[governanceChangeCount] = GovernanceRecord({
            changeId: governanceChangeCount,
            changeType: _changeType,
            description: _description,
            beforeHash: _beforeHash,
            afterHash: _afterHash,
            timestamp: block.timestamp,
            actor: msg.sender
        });

        emit GovernanceChangeLogged(
            governanceChangeCount,
            _changeType,
            _description,
            block.timestamp
        );
    }

    // ═══════════════════════════════════════════════════════════
    // VIEW FUNCTIONS (FOR OFF-CHAIN QUERIES)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Get daily summary.
     * @param _epochDay The epoch day (block.timestamp / 1 days)
     * @return trades_ Number of trades that day
     * @return pnl_ P&L that day in wei
     */
    function getDailySummary(uint256 _epochDay)
        external
        view
        returns (uint256 trades_, int256 pnl_)
    {
        return (dailyTradeCount[_epochDay], dailyPnl[_epochDay]);
    }

    /**
     * @notice Get symbol summary.
     * @param _symbolHash The symbol hash
     * @return trades_ Total trades for this symbol
     * @return pnl_ Cumulative P&L for this symbol
     * @return latestTradeId_ ID of the most recent trade
     */
    function getSymbolSummary(bytes32 _symbolHash)
        external
        view
        returns (uint256 trades_, int256 pnl_, uint256 latestTradeId_)
    {
        return (
            symbolTradeCount[_symbolHash],
            symbolPnl[_symbolHash],
            latestTradeBySymbol[_symbolHash]
        );
    }

    /**
     * @notice Get the latest N trade IDs for pagination.
     * @param _count Number of recent trades to return
     * @return tradeIds Array of trade IDs (most recent first)
     */
    function getRecentTradeIds(uint256 _count)
        external
        view
        returns (uint256[] memory tradeIds)
    {
        uint256 total = tradeCount;
        uint256 limit_ = _count > total ? total : _count;
        tradeIds = new uint256[](limit_);

        for (uint256 i = 0; i < limit_; i++) {
            tradeIds[i] = total - i;
        }
    }
}
