// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TSARMandate
 * @notice On-chain trading mandate — defines WHAT the system is allowed to trade.
 * @dev Stored as immutable smart contract state. Changes require governance vote.
 *
 * MANDATE = HUMAN COMMITMENT ON-CHAIN
 *   - Allowed symbols: which pairs can be traded
 *   - Max leverage: per-symbol leverage limits
 *   - Position limits: max single position, max total exposure
 *   - Order types: market, limit, stop_market, stop_limit
 *   - Daily trade limits: prevent overtrading
 *
 * GOVERNANCE:
 *   - Valentine controls rules via wallet
 *   - Changes require transaction signing
 *   - Critical changes require multi-sig (2-of-3)
 *   - All changes have 48h time-lock
 *   - Immutable audit trail of all mandate changes
 *
 * INTEGRATION WITH TSAR:
 *   - Python Mandate class reads on-chain state via Rust bridge
 *   - Off-chain: Python validates orders against mandate
 *   - On-chain: Smart contract verifies mandate compliance
 *   - If on-chain mandate says "symbol not allowed", order REJECTED
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract TSARMandate is AccessControl, ReentrancyGuard {
    // ═══════════════════════════════════════════════════════════
    // ROLES
    // ═══════════════════════════════════════════════════════════

    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");

    // ═══════════════════════════════════════════════════════════
    // TYPES
    // ═══════════════════════════════════════════════════════════

    /// @notice Mandate lifecycle status
    enum MandateStatus {
        DRAFT,      // Created but not committed
        ACTIVE,     // Committed and enforcing
        REVOKED     // Deactivated
    }

    /// @notice Order types allowed by the mandate
    enum OrderType {
        MARKET,
        LIMIT,
        STOP_MARKET,
        STOP_LIMIT
    }

    /// @notice Single mandate rule set
    struct MandateRules {
        bytes32[] allowedSymbols;       // Hashed symbol identifiers
        uint256 maxPositionSizeBps;     // Max position as bps of equity (1500 = 15%)
        uint256 maxDailyTrades;         // Max trades per day
        uint256 maxLeverageBps;         // Max leverage in bps (300 = 3x)
        uint256 maxNotionalPerTrade;    // Max notional per trade (in wei)
        uint256 maxTotalExposureBps;    // Max total exposure as bps (10000 = 100%)
        bool allowMarketOrders;
        bool allowLimitOrders;
        bool allowStopOrders;
        bool allowShortSelling;
        uint256 minPaperTrades;         // Min paper trades before live
        uint256 minPaperDays;           // Min days in paper mode
        uint256 minWinRateBps;          // Min win rate in bps (5500 = 55%)
    }

    /// @notice Full mandate state
    struct MandateState {
        MandateStatus status;
        uint256 version;
        uint256 committedAt;
        address committedBy;
        uint256 revokedAt;
        address revokedBy;
        string notes;
    }

    /// @notice Mandate change proposal
    struct MandateProposal {
        uint256 nonce;
        address proposer;
        uint256 proposedAt;
        MandateRules newRules;
        string changeDescription;
        uint256 confirmations;
        mapping(address => bool) hasConfirmed;
        bool executed;
    }

    // ═══════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════

    /// @notice Current mandate rules
    MandateRules public currentRules;

    /// @notice Current mandate state
    MandateState public mandateState;

    /// @notice Mandate change proposals
    mapping(uint256 => MandateProposal) public proposals;

    /// @notice Current proposal nonce
    uint256 public proposalNonce;

    /// @notice Time-lock for mandate changes (48 hours)
    uint256 public constant MANDATE_CHANGE_TIMELOCK = 48 hours;

    /// @notice Required confirmations for mandate changes (2-of-3)
    uint256 public constant REQUIRED_CONFIRMATIONS = 2;

    /// @notice Symbol registry: symbol hash => symbol string
    mapping(bytes32 => string) public symbolRegistry;

    /// @notice Paper trading tracking
    uint256 public paperTradesCompleted;
    uint256 public paperWins;
    uint256 public paperStartDate;

    // ═══════════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════════

    event MandateCommitted(
        uint256 version,
        address committedBy,
        uint256 timestamp
    );

    event MandateRevoked(
        uint256 version,
        address revokedBy,
        uint256 timestamp
    );

    event MandateChangeProposed(
        uint256 nonce,
        address proposer,
        string changeDescription,
        uint256 timestamp
    );

    event MandateChangeConfirmed(
        uint256 nonce,
        address confirmer,
        uint256 confirmations
    );

    event MandateChangeExecuted(
        uint256 nonce,
        uint256 newVersion,
        uint256 timestamp
    );

    event OrderChecked(
        bytes32 symbolHash,
        uint256 orderType,
        bool allowed,
        string reason
    );

    event PaperTradeRecorded(
        bool isWin,
        uint256 totalTrades,
        uint256 totalWins
    );

    // ═══════════════════════════════════════════════════════════
    // ERRORS
    // ═══════════════════════════════════════════════════════════

    error MandateNotActive();
    error SymbolNotAllowed(bytes32 symbolHash);
    error OrderTypeNotAllowed(uint256 orderType);
    error LeverageExceeded(uint256 requested, uint256 max);
    error PositionSizeExceeded(uint256 notionalBps, uint256 maxBps);
    error TotalExposureExceeded(uint256 exposureBps, uint256 maxBps);
    error DailyTradesExceeded(uint256 current, uint256 max);
    error ShortSellingNotAllowed();
    error PaperTradingRequirementsNotMet(string reason);
    error InvalidProposal(uint256 nonce);
    error AlreadyConfirmed(address signer);
    error InsufficientConfirmations(uint256 have, uint256 need);
    error TimelockNotExpired(uint256 expiresAt, uint256 now);

    // ═══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════════════════════

    constructor(address _governance) {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(GOVERNANCE_ROLE, _governance);
        _grantRole(OPERATOR_ROLE, msg.sender);

        mandateState.status = MandateStatus.DRAFT;
        mandateState.version = 1;
    }

    // ═══════════════════════════════════════════════════════════
    // MANDATE LIFECYCLE
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Set initial mandate rules (DRAFT state).
     * @param _rules The initial mandate rules.
     * @param _notes Description of the mandate.
     */
    function setInitialRules(MandateRules calldata _rules, string calldata _notes)
        external
        onlyRole(GOVERNANCE_ROLE)
    {
        require(mandateState.status == MandateStatus.DRAFT, "Already initialized");

        currentRules = _rules;
        mandateState.notes = _notes;
    }

    /**
     * @notice Commit the mandate — human signs off, becomes ACTIVE.
     * @dev A committed mandate is a CONTRACT. The system will enforce
     *      these rules until explicitly revoked or updated.
     */
    function commit() external onlyRole(GOVERNANCE_ROLE) {
        require(mandateState.status == MandateStatus.DRAFT, "Not in DRAFT state");
        require(currentRules.allowedSymbols.length > 0, "No symbols configured");

        // Check paper trading requirements
        _checkPaperTradingRequirements();

        mandateState.status = MandateStatus.ACTIVE;
        mandateState.committedAt = block.timestamp;
        mandateState.committedBy = msg.sender;
        mandateState.revokedAt = 0;
        mandateState.revokedBy = address(0);

        emit MandateCommitted(mandateState.version, msg.sender, block.timestamp);
    }

    /**
     * @notice Revoke the mandate — deactivate, block all live trades.
     */
    function revoke() external onlyRole(GOVERNANCE_ROLE) {
        require(mandateState.status == MandateStatus.ACTIVE, "Not ACTIVE");

        mandateState.status = MandateStatus.REVOKED;
        mandateState.revokedAt = block.timestamp;
        mandateState.revokedBy = msg.sender;

        emit MandateRevoked(mandateState.version, msg.sender, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // MANDATE CHANGES (GOVERNANCE)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Propose a mandate change.
     * @dev Changes require multi-sig + time-lock for safety.
     * @param _newRules The proposed new rules.
     * @param _changeDescription What changed and why.
     */
    function proposeMandateChange(
        MandateRules calldata _newRules,
        string calldata _changeDescription
    ) external onlyRole(GOVERNANCE_ROLE) {
        proposalNonce++;

        MandateProposal storage proposal = proposals[proposalNonce];
        proposal.nonce = proposalNonce;
        proposal.proposer = msg.sender;
        proposal.proposedAt = block.timestamp;
        proposal.newRules = _newRules;
        proposal.changeDescription = _changeDescription;
        proposal.confirmations = 0;
        proposal.executed = false;

        emit MandateChangeProposed(
            proposalNonce,
            msg.sender,
            _changeDescription,
            block.timestamp
        );
    }

    /**
     * @notice Confirm a mandate change proposal.
     * @param _nonce The proposal nonce to confirm.
     */
    function confirmMandateChange(uint256 _nonce) external onlyRole(GOVERNANCE_ROLE) {
        MandateProposal storage proposal = proposals[_nonce];
        if (proposal.nonce == 0) revert InvalidProposal(_nonce);
        if (proposal.hasConfirmed[msg.sender]) revert AlreadyConfirmed(msg.sender);

        proposal.hasConfirmed[msg.sender] = true;
        proposal.confirmations++;

        emit MandateChangeConfirmed(_nonce, msg.sender, proposal.confirmations);
    }

    /**
     * @notice Execute a confirmed mandate change after timelock.
     * @param _nonce The proposal nonce to execute.
     */
    function executeMandateChange(uint256 _nonce) external nonReentrant {
        MandateProposal storage proposal = proposals[_nonce];
        if (proposal.nonce == 0) revert InvalidProposal(_nonce);
        if (proposal.executed) revert InvalidProposal(_nonce);

        // Check confirmations
        if (proposal.confirmations < REQUIRED_CONFIRMATIONS) {
            revert InsufficientConfirmations(proposal.confirmations, REQUIRED_CONFIRMATIONS);
        }

        // Check timelock
        uint256 unlockTime = proposal.proposedAt + MANDATE_CHANGE_TIMELOCK;
        if (block.timestamp < unlockTime) {
            revert TimelockNotExpired(unlockTime, block.timestamp);
        }

        // Execute change
        currentRules = proposal.newRules;
        mandateState.version++;
        proposal.executed = true;

        // Re-commit mandate
        mandateState.status = MandateStatus.ACTIVE;
        mandateState.committedAt = block.timestamp;
        mandateState.committedBy = msg.sender;

        emit MandateChangeExecuted(_nonce, mandateState.version, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // ORDER CHECKING (THE CORE ENFORCEMENT)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Check if an order complies with the mandate.
     * @dev This is THE enforcement function. Called before every trade.
     *      Returns (allowed, reason) — if not allowed, trade CANNOT proceed.
     * @param _symbolHash Hash of the trading pair (keccak256("BTC/USDT"))
     * @param _orderType Order type (0=MARKET, 1=LIMIT, 2=STOP_MARKET, 3=STOP_LIMIT)
     * @param _side 0=BUY, 1=SELL
     * @param _notionalBps Trade notional as bps of equity
     * @param _leverageBps Requested leverage in bps
     * @param _dailyTradeCount Current daily trade count
     * @return allowed Whether the order passes mandate checks
     * @return reason Human-readable reason (empty if allowed)
     */
    function checkOrder(
        bytes32 _symbolHash,
        uint256 _orderType,
        uint256 _side,
        uint256 _notionalBps,
        uint256 _leverageBps,
        uint256 _dailyTradeCount
    ) external returns (bool allowed, string memory reason) {
        // Must be ACTIVE
        if (mandateState.status != MandateStatus.ACTIVE) {
            emit OrderChecked(_symbolHash, _orderType, false, "Mandate not ACTIVE");
            return (false, "Mandate is not ACTIVE");
        }

        // Check symbol
        if (!_isSymbolAllowed(_symbolHash)) {
            string memory symbol = symbolRegistry[_symbolHash];
            emit OrderChecked(_symbolHash, _orderType, false, "Symbol not allowed");
            return (false, string.concat("Symbol '", symbol, "' not in allowed list"));
        }

        // Check order type
        if (!_isOrderTypeAllowed(_orderType)) {
            emit OrderChecked(_symbolHash, _orderType, false, "Order type not allowed");
            return (false, "Order type not allowed by mandate");
        }

        // Check short selling
        if (_side == 1 && !currentRules.allowShortSelling) {
            emit OrderChecked(_symbolHash, _orderType, false, "Short selling not allowed");
            return (false, "Short selling not allowed by mandate");
        }

        // Check position size
        if (_notionalBps > currentRules.maxPositionSizeBps) {
            emit OrderChecked(_symbolHash, _orderType, false, "Position size exceeded");
            return (false, "Position size exceeds mandate limit");
        }

        // Check leverage
        if (_leverageBps > currentRules.maxLeverageBps) {
            emit OrderChecked(_symbolHash, _orderType, false, "Leverage exceeded");
            return (false, "Leverage exceeds mandate limit");
        }

        // Check daily trades
        if (currentRules.maxDailyTrades > 0 && _dailyTradeCount >= currentRules.maxDailyTrades) {
            emit OrderChecked(_symbolHash, _orderType, false, "Daily trades exceeded");
            return (false, "Daily trade limit reached");
        }

        emit OrderChecked(_symbolHash, _orderType, true, "");
        return (true, "");
    }

    // ═══════════════════════════════════════════════════════════
    // PAPER TRADING TRACKING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Record a paper trade outcome.
     * @param _isWin Whether the trade was profitable.
     */
    function recordPaperTrade(bool _isWin) external onlyRole(OPERATOR_ROLE) {
        paperTradesCompleted++;
        if (_isWin) paperWins++;
        if (paperStartDate == 0) paperStartDate = block.timestamp;

        emit PaperTradeRecorded(_isWin, paperTradesCompleted, paperWins);
    }

    // ═══════════════════════════════════════════════════════════
    // VIEW FUNCTIONS
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Check if a symbol is in the allowed list.
     * @param _symbolHash Hash of the symbol.
     * @return True if symbol is allowed.
     */
    function isSymbolAllowed(bytes32 _symbolHash) external view returns (bool) {
        return _isSymbolAllowed(_symbolHash);
    }

    /**
     * @notice Get current mandate version.
     * @return version The mandate version number.
     * @return status The mandate status.
     */
    function getMandateVersion() external view returns (uint256 version, MandateStatus status) {
        return (mandateState.version, mandateState.status);
    }

    /**
     * @notice Get paper trading status.
     * @return trades Total paper trades
     * @return wins Total wins
     * @return winRateBps Win rate in basis points
     * @return daysInPaper Days since paper trading started
     */
    function getPaperTradingStatus()
        external
        view
        returns (
            uint256 trades,
            uint256 wins,
            uint256 winRateBps,
            uint256 daysInPaper
        )
    {
        trades = paperTradesCompleted;
        wins = paperWins;
        winRateBps = paperTradesCompleted > 0
            ? (paperWins * 10000) / paperTradesCompleted
            : 0;
        daysInPaper = paperStartDate > 0
            ? (block.timestamp - paperStartDate) / 1 days
            : 0;
    }

    // ═══════════════════════════════════════════════════════════
    // SYMBOL REGISTRY
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Register a symbol hash to its string representation.
     * @param _symbolHash Hash of the symbol.
     * @param _symbol The symbol string (e.g., "BTC/USDT").
     */
    function registerSymbol(bytes32 _symbolHash, string calldata _symbol)
        external
        onlyRole(GOVERNANCE_ROLE)
    {
        symbolRegistry[_symbolHash] = _symbol;
    }

    // ═══════════════════════════════════════════════════════════
    // INTERNAL
    // ═══════════════════════════════════════════════════════════

    function _isSymbolAllowed(bytes32 _symbolHash) internal view returns (bool) {
        for (uint256 i = 0; i < currentRules.allowedSymbols.length; i++) {
            if (currentRules.allowedSymbols[i] == _symbolHash) {
                return true;
            }
        }
        return false;
    }

    function _isOrderTypeAllowed(uint256 _orderType) internal view returns (bool) {
        if (_orderType == 0) return currentRules.allowMarketOrders;
        if (_orderType == 1) return currentRules.allowLimitOrders;
        if (_orderType == 2 || _orderType == 3) return currentRules.allowStopOrders;
        return false;
    }

    function _checkPaperTradingRequirements() internal view {
        if (currentRules.minPaperTrades > 0 && paperTradesCompleted < currentRules.minPaperTrades) {
            revert PaperTradingRequirementsNotMet(
                string.concat(
                    "Insufficient paper trades: need ",
                    uint2str(currentRules.minPaperTrades),
                    ", have ",
                    uint2str(paperTradesCompleted)
                )
            );
        }

        if (currentRules.minPaperDays > 0 && paperStartDate > 0) {
            uint256 daysInPaper = (block.timestamp - paperStartDate) / 1 days;
            if (daysInPaper < currentRules.minPaperDays) {
                revert PaperTradingRequirementsNotMet(
                    string.concat(
                        "Insufficient paper days: need ",
                        uint2str(currentRules.minPaperDays),
                        ", have ",
                        uint2str(daysInPaper)
                    )
                );
            }
        }

        if (currentRules.minWinRateBps > 0 && paperTradesCompleted > 0) {
            uint256 winRateBps = (paperWins * 10000) / paperTradesCompleted;
            if (winRateBps < currentRules.minWinRateBps) {
                revert PaperTradingRequirementsNotMet(
                    string.concat(
                        "Win rate insufficient: need ",
                        uint2str(currentRules.minWinRateBps),
                        " bps, have ",
                        uint2str(winRateBps),
                        " bps"
                    )
                );
            }
        }
    }

    function uint2str(uint256 value) internal pure returns (string memory) {
        if (value == 0) return "0";
        bytes memory buffer = new bytes(78);
        uint256 i = 78;
        while (value > 0) {
            buffer[--i] = bytes1(uint8(48 + (value % 10)));
            value /= 10;
        }
        return string(buffer[i:]);
    }
}
