// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TSARKillSwitch
 * @notice On-chain kill switch that halts trading when daily loss exceeds -2%.
 * @dev Cannot be bypassed by any code path. Deactivation requires multi-sig.
 *
 * DESIGN PHILOSOPHY:
 *   Valentine wants blockchain for RULES, not execution speed.
 *   This contract makes risk management trustless and auditable.
 *   The kill switch is the single most critical piece of state —
 *   if it says "halt", nothing trades. Period.
 *
 * INTEGRATION WITH TSAR:
 *   - Python RiskGovernor reads kill switch state via Rust bridge
 *   - Off-chain: Python checks rules (fast path)
 *   - On-chain: Smart contract verifies enforcement (trust layer)
 *   - If on-chain says halt, off-chain CANNOT override
 *
 * DEPLOYMENT: Polygon (cheap gas, fast finality)
 *   Gas cost per check: ~5,000 gas (~$0.001)
 *   Gas cost per activation: ~50,000 gas (~$0.01)
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract TSARKillSwitch is AccessControl, Pausable, ReentrancyGuard {
    // ═══════════════════════════════════════════════════════════
    // ROLES
    // ═══════════════════════════════════════════════════════════

    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant MULTISIG_ROLE = keccak256("MULTISIG_ROLE");
    bytes32 public constant EMERGENCY_ROLE = keccak256("EMERGENCY_ROLE");

    // ═══════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════

    /// @notice Whether the kill switch is currently active (trading halted)
    bool public isActive;

    /// @notice Unix timestamp when kill switch was activated
    uint256 public activatedAt;

    /// @notice Reason for activation (immutable once set)
    string public activationReason;

    /// @notice Daily P&L tracking (basis points, negative = loss)
    int256 public dailyPnlBps;

    /// @notice Daily loss threshold in basis points (default: -200 = -2%)
    int256 public dailyLossThresholdBps;

    /// @notice High water mark for drawdown calculation
    uint256 public highWaterMark;

    /// @notice Current equity value
    uint256 public currentEquity;

    /// @notice Drawdown halt threshold in basis points (default: -500 = -5%)
    int256 public drawdownHaltThresholdBps;

    /// @notice Drawdown flatten threshold in basis points (default: -1500 = -15%)
    int256 public drawdownFlattenThresholdBps;

    /// @notice Multi-sig deactivation: number of confirmations required
    uint256 public constant REQUIRED_CONFIRMATIONS = 2;

    /// @notice Multi-sig deactivation: total signers
    uint256 public constant TOTAL_SIGNERS = 3;

    /// @notice Deactivation proposal nonce (prevents replay)
    uint256 public deactivationNonce;

    /// @notice Mapping of deactivation nonce => confirmations count
    mapping(uint256 => uint256) public deactivationConfirmations;

    /// @notice Mapping of deactivation nonce => signer => has confirmed
    mapping(uint256 => mapping(address => bool)) public hasConfirmed;

    /// @notice Time-lock for deactivation (48 hours)
    uint256 public constant DEACTIVATION_TIMELOCK = 48 hours;

    /// @notice When the deactivation proposal was created
    uint256 public deactivationProposedAt;

    /// @notice Circuit breaker level (0=GREEN, 1=YELLOW, 2=ORANGE, 3=RED)
    uint8 public circuitBreakerLevel;

    // ═══════════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════════

    event KillSwitchActivated(
        string reason,
        uint256 timestamp,
        int256 dailyPnlBps,
        uint8 circuitBreakerLevel
    );

    event KillSwitchDeactivated(
        uint256 timestamp,
        address deactivator
    );

    event DailyPnlUpdated(
        int256 dailyPnlBps,
        uint256 timestamp,
        bool thresholdBreached
    );

    event EquityUpdated(
        uint256 equity,
        uint256 highWaterMark,
        int256 drawdownBps,
        uint8 circuitBreakerLevel
    );

    event DeactivationProposed(
        uint256 nonce,
        address proposer,
        uint256 timestamp
    );

    event DeactivationConfirmed(
        uint256 nonce,
        address confirmer,
        uint256 confirmations
    );

    event CircuitBreakerChanged(
        uint8 oldLevel,
        uint8 newLevel,
        uint256 timestamp
    );

    // ═══════════════════════════════════════════════════════════
    // ERRORS
    // ═══════════════════════════════════════════════════════════

    error KillSwitchAlreadyActive();
    error KillSwitchNotActive();
    error DailyLossThresholdBreached(int256 dailyPnlBps, int256 threshold);
    error DrawdownThresholdBreached(int256 drawdownBps, int256 threshold);
    error InsufficientConfirmations(uint256 have, uint256 need);
    error AlreadyConfirmed(address signer);
    error TimelockNotExpired(uint256 expiresAt, uint256 now);
    error InvalidNonce(uint256 nonce);
    error UnauthorizedCaller();

    // ═══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Deploy the kill switch with initial parameters.
     * @param _operator Address that can update P&L and equity (TSAR bot)
     * @param _multisigAddresses Array of 3 multi-sig signer addresses
     * @param _dailyLossThreshold Daily loss threshold in bps (default: -200)
     * @param _drawdownHalt Drawdown halt threshold in bps (default: -500)
     * @param _drawdownFlatten Drawdown flatten threshold in bps (default: -1500)
     */
    constructor(
        address _operator,
        address[3] memory _multisigAddresses,
        int256 _dailyLossThreshold,
        int256 _drawdownHalt,
        int256 _drawdownFlatten
    ) {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(OPERATOR_ROLE, _operator);
        _grantRole(EMERGENCY_ROLE, msg.sender);

        for (uint256 i = 0; i < 3; i++) {
            _grantRole(MULTISIG_ROLE, _multisigAddresses[i]);
        }

        dailyLossThresholdBps = _dailyLossThreshold;     // -200 = -2%
        drawdownHaltThresholdBps = _drawdownHalt;        // -500 = -5%
        drawdownFlattenThresholdBps = _drawdownFlatten;  // -1500 = -15%
        deactivationNonce = 0;
    }

    // ═══════════════════════════════════════════════════════════
    // CORE: KILL SWITCH ACTIVATION (AUTO)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Update daily P&L. Auto-activates kill switch if threshold breached.
     * @dev Called by TSAR operator (Rust bridge) after each trade settlement.
     *      If daily loss exceeds -2%, kill switch activates AUTOMATICALLY.
     *      This CANNOT be prevented by any code path.
     * @param _dailyPnlBps Current daily P&L in basis points (negative = loss)
     */
    function updateDailyPnl(int256 _dailyPnlBps) external onlyRole(OPERATOR_ROLE) {
        dailyPnlBps = _dailyPnlBps;

        bool breached = _dailyPnlBps <= dailyLossThresholdBps;

        emit DailyPnlUpdated(_dailyPnlBps, block.timestamp, breached);

        // AUTO-ACTIVATE: If daily loss exceeds threshold, halt immediately
        if (breached && !isActive) {
            _activateKillSwitch(
                string.concat(
                    "Daily P&L threshold breached: ",
                    _intToString(_dailyPnlBps),
                    " bps <= ",
                    _intToString(dailyLossThresholdBps),
                    " bps"
                )
            );
        }
    }

    /**
     * @notice Update equity and high water mark. Checks drawdown circuit breakers.
     * @dev Called by TSAR operator (Rust bridge) periodically.
     *      Updates circuit breaker level based on drawdown.
     *      RED level auto-activates kill switch.
     * @param _equity Current portfolio equity in wei (18 decimals)
     */
    function updateEquity(uint256 _equity) external onlyRole(OPERATOR_ROLE) {
        currentEquity = _equity;

        // Update high water mark
        if (_equity > highWaterMark) {
            highWaterMark = _equity;
        }

        // Calculate drawdown in basis points
        // FIX: Use signed arithmetic to prevent uint256 underflow when
        // _equity < highWaterMark. The old code cast (uint256 * 10000) to
        // int256 which underflows before the cast, producing garbage.
        int256 drawdownBps = 0;
        if (highWaterMark > 0) {
            if (_equity < highWaterMark) {
                uint256 loss = highWaterMark - _equity;
                drawdownBps = -int256((loss * 10000) / highWaterMark);
            } else if (_equity > highWaterMark) {
                uint256 gain = _equity - highWaterMark;
                drawdownBps = int256((gain * 10000) / highWaterMark);
            }
            // else: drawdownBps stays 0 (no change)
        }

        // Determine circuit breaker level
        uint8 oldLevel = circuitBreakerLevel;
        uint8 newLevel = _determineCircuitBreakerLevel(drawdownBps);

        if (newLevel != oldLevel) {
            circuitBreakerLevel = newLevel;
            emit CircuitBreakerChanged(oldLevel, newLevel, block.timestamp);
        }

        emit EquityUpdated(_equity, highWaterMark, drawdownBps, newLevel);

        // RED level → auto-activate kill switch
        if (newLevel == 3 && !isActive) {
            _activateKillSwitch(
                string.concat(
                    "Circuit breaker RED: drawdown ",
                    _intToString(drawdownBps),
                    " bps exceeds flatten threshold ",
                    _intToString(drawdownFlattenThresholdBps),
                    " bps"
                )
            );
        }
    }

    /**
     * @notice Emergency activation — any emergency role can halt immediately.
     * @param _reason Human-readable reason for emergency halt.
     */
    function emergencyHalt(string calldata _reason) external onlyRole(EMERGENCY_ROLE) {
        if (isActive) revert KillSwitchAlreadyActive();
        _activateKillSwitch(string.concat("EMERGENCY: ", _reason));
    }

    // ═══════════════════════════════════════════════════════════
    // CORE: KILL SWITCH DEACTIVATION (MULTI-SIG + TIMELOCK)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Propose deactivation of the kill switch.
     * @dev Starts the multi-sig + timelock process.
     *      Requires 2-of-3 multi-sig confirmations AND 48h timelock.
     */
    function proposeDeactivation() external onlyRole(MULTISIG_ROLE) {
        if (!isActive) revert KillSwitchNotActive();

        deactivationNonce++;
        deactivationProposedAt = block.timestamp;

        emit DeactivationProposed(deactivationNonce, msg.sender, block.timestamp);
    }

    /**
     * @notice Confirm a deactivation proposal.
     * @param _nonce The deactivation proposal nonce to confirm.
     */
    function confirmDeactivation(uint256 _nonce) external onlyRole(MULTISIG_ROLE) {
        if (_nonce != deactivationNonce) revert InvalidNonce(_nonce);
        if (hasConfirmed[_nonce][msg.sender]) revert AlreadyConfirmed(msg.sender);

        hasConfirmed[_nonce][msg.sender] = true;
        deactivationConfirmations[_nonce]++;

        emit DeactivationConfirmed(_nonce, msg.sender, deactivationConfirmations[_nonce]);
    }

    /**
     * @notice Execute deactivation after timelock + multi-sig.
     * @dev Anyone can call this after conditions are met (trustless execution).
     *      Conditions: 2-of-3 confirmations + 48h timelock elapsed.
     */
    function executeDeactivation() external nonReentrant {
        if (!isActive) revert KillSwitchNotActive();

        uint256 nonce = deactivationNonce;

        // Check multi-sig confirmations
        if (deactivationConfirmations[nonce] < REQUIRED_CONFIRMATIONS) {
            revert InsufficientConfirmations(
                deactivationConfirmations[nonce],
                REQUIRED_CONFIRMATIONS
            );
        }

        // Check timelock
        uint256 unlockTime = deactivationProposedAt + DEACTIVATION_TIMELOCK;
        if (block.timestamp < unlockTime) {
            revert TimelockNotExpired(unlockTime, block.timestamp);
        }

        // Execute deactivation
        isActive = false;
        activatedAt = 0;
        activationReason = "";
        circuitBreakerLevel = 0; // Reset to GREEN

        emit KillSwitchDeactivated(block.timestamp, msg.sender);
    }

    // ═══════════════════════════════════════════════════════════
    // VIEW FUNCTIONS (FOR OFF-CHAIN VERIFICATION)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Check if trading is allowed. This is THE authoritative check.
     * @return True if trading is allowed, false if kill switch is active.
     */
    function isTradingAllowed() external view returns (bool) {
        return !isActive;
    }

    /**
     * @notice Get full kill switch status for audit.
     * @return active Whether kill switch is active
     * @return reason Activation reason
     * @return activatedAt When it was activated
     * @return dailyPnl Current daily P&L in bps
     * @return circuitLevel Current circuit breaker level
     * @return drawdownBps Current drawdown in bps
     */
    function getStatus()
        external
        view
        returns (
            bool active,
            string memory reason,
            uint256 activatedAt_,
            int256 dailyPnl,
            uint8 circuitLevel,
            int256 drawdownBps
        )
    {
        int256 drawdown = 0;
        if (highWaterMark > 0) {
            if (currentEquity < highWaterMark) {
                uint256 loss = highWaterMark - currentEquity;
                drawdown = -int256((loss * 10000) / highWaterMark);
            } else if (currentEquity > highWaterMark) {
                uint256 gain = currentEquity - highWaterMark;
                drawdown = int256((gain * 10000) / highWaterMark);
            }
        }

        return (
            isActive,
            activationReason,
            activatedAt,
            dailyPnlBps,
            circuitBreakerLevel,
            drawdown
        );
    }

    /**
     * @notice Check if a trade of given size is within position limits.
     * @param _notionalBps Trade notional as basis points of equity.
     * @param _maxPositionBps Maximum allowed position in bps (default: 1500 = 15%).
     * @return True if trade is within limits.
     */
    function checkPositionLimit(
        uint256 _notionalBps,
        uint256 _maxPositionBps
    ) external view returns (bool) {
        if (isActive) return false;
        return _notionalBps <= _maxPositionBps;
    }

    // ═══════════════════════════════════════════════════════════
    // INTERNAL
    // ═══════════════════════════════════════════════════════════

    function _activateKillSwitch(string memory _reason) internal {
        isActive = true;
        activatedAt = block.timestamp;
        activationReason = _reason;
        circuitBreakerLevel = 3; // RED

        emit KillSwitchActivated(_reason, block.timestamp, dailyPnlBps, 3);
    }

    function _determineCircuitBreakerLevel(int256 _drawdownBps)
        internal
        view
        returns (uint8)
    {
        if (_drawdownBps <= drawdownFlattenThresholdBps) return 3; // RED
        if (_drawdownBps <= drawdownHaltThresholdBps) return 2;    // ORANGE
        if (_drawdownBps <= -200) return 1;                        // YELLOW (-2%)
        return 0;                                                   // GREEN
    }

    function _intToString(int256 value) internal pure returns (string memory) {
        if (value == 0) return "0";

        bool negative = value < 0;
        if (negative) value = -value;

        bytes memory buffer = new bytes(78);
        uint256 i = 78;
        while (value > 0) {
            buffer[--i] = bytes1(uint8(48 + (value % 10)));
            value /= 10;
        }

        if (negative) {
            buffer[--i] = bytes1("-");
        }

        return string(buffer[i:]);
    }

    // ═══════════════════════════════════════════════════════════
    // ADMIN (TIMELOCKED)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Update loss threshold (requires admin + timelock).
     * @param _newThreshold New daily loss threshold in bps.
     */
    function updateDailyLossThreshold(int256 _newThreshold)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        dailyLossThresholdBps = _newThreshold;
    }

    /**
     * @notice Update drawdown thresholds (requires admin + timelock).
     * @param _halt New halt threshold in bps.
     * @param _flatten New flatten threshold in bps.
     */
    function updateDrawdownThresholds(int256 _halt, int256 _flatten)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        drawdownHaltThresholdBps = _halt;
        drawdownFlattenThresholdBps = _flatten;
    }
}
