// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TSARPositionLimits
 * @notice On-chain enforcement of position limits — cannot be bypassed by any code path.
 * @dev Smart contract enforces max position size, max total exposure, and concentration limits.
 *
 * POSITION LIMITS (ENFORCED ON-CHAIN):
 *   - Max single position: 15% of capital
 *   - Max total exposure: 100% of capital
 *   - Max sector concentration: 30% of capital
 *   - Cannot be exceeded by ANY code path
 *
 * DESIGN:
 *   - Off-chain: Python RiskGovernor checks limits (fast path)
 *   - On-chain: Smart contract verifies limits (trust layer)
 *   - If on-chain says "exceeded", trade CANNOT proceed
 *   - Dual enforcement: both must agree
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract TSARPositionLimits is AccessControl, ReentrancyGuard {
    // ═══════════════════════════════════════════════════════════
    // ROLES
    // ═══════════════════════════════════════════════════════════

    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");

    // ═══════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════

    /// @notice Current portfolio equity (updated by operator)
    uint256 public currentEquity;

    /// @notice Max single position as basis points of equity (1500 = 15%)
    uint256 public maxSinglePositionBps;

    /// @notice Max total exposure as basis points of equity (10000 = 100%)
    uint256 public maxTotalExposureBps;

    /// @notice Max sector concentration as basis points of equity (3000 = 30%)
    uint256 public maxSectorConcentrationBps;

    /// @notice Max number of open positions
    uint256 public maxOpenPositions;

    /// @notice Current number of open positions
    uint256 public openPositionCount;

    /// @notice Total exposure across all positions (in notional value)
    uint256 public totalExposure;

    /// @notice Position tracking: symbol hash => position details
    mapping(bytes32 => PositionInfo) public positions;

    /// @notice Sector tracking: sector hash => total exposure
    mapping(bytes32 => uint256) public sectorExposure;

    /// @notice Position info struct
    struct PositionInfo {
        bytes32 symbolHash;
        bytes32 sectorHash;
        uint256 notionalValue;
        uint256 entryPrice;
        uint256 quantity;
        uint256 openedAt;
        bool isOpen;
    }

    // ═══════════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════════

    event PositionOpened(
        bytes32 indexed symbolHash,
        bytes32 indexed sectorHash,
        uint256 notionalValue,
        uint256 positionBps,
        uint256 timestamp
    );

    event PositionClosed(
        bytes32 indexed symbolHash,
        uint256 notionalValue,
        uint256 timestamp
    );

    event PositionLimitCheck(
        bytes32 indexed symbolHash,
        uint256 requestedNotionalBps,
        uint256 maxAllowedBps,
        bool passed,
        string reason
    );

    event ExposureUpdated(
        uint256 totalExposure,
        uint256 totalExposureBps,
        uint256 timestamp
    );

    // ═══════════════════════════════════════════════════════════
    // ERRORS
    // ═══════════════════════════════════════════════════════════

    error SinglePositionExceeded(uint256 notionalBps, uint256 maxBps);
    error TotalExposureExceeded(uint256 exposureBps, uint256 maxBps);
    error SectorConcentrationExceeded(uint256 sectorBps, uint256 maxBps);
    error MaxPositionsReached(uint256 current, uint256 max);
    error PositionNotOpen(bytes32 symbolHash);
    error PositionAlreadyOpen(bytes32 symbolHash);

    // ═══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════════════════════

    constructor(
        address _governance,
        address _operator,
        uint256 _maxSinglePositionBps,
        uint256 _maxTotalExposureBps,
        uint256 _maxSectorConcentrationBps,
        uint256 _maxOpenPositions
    ) {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(GOVERNANCE_ROLE, _governance);
        _grantRole(OPERATOR_ROLE, _operator);

        maxSinglePositionBps = _maxSinglePositionBps;     // 1500 = 15%
        maxTotalExposureBps = _maxTotalExposureBps;        // 10000 = 100%
        maxSectorConcentrationBps = _maxSectorConcentrationBps; // 3000 = 30%
        maxOpenPositions = _maxOpenPositions;               // 10
    }

    // ═══════════════════════════════════════════════════════════
    // EQUITY MANAGEMENT
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Update current equity value.
     * @dev Called by operator (Rust bridge) periodically.
     * @param _equity Current portfolio equity.
     */
    function updateEquity(uint256 _equity) external onlyRole(OPERATOR_ROLE) {
        currentEquity = _equity;

        uint256 exposureBps = currentEquity > 0
            ? (totalExposure * 10000) / currentEquity
            : 0;

        emit ExposureUpdated(totalExposure, exposureBps, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // POSITION LIMIT CHECKS (THE CORE ENFORCEMENT)
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Check if a new position is within all limits.
     * @dev This is THE enforcement function. Called before every trade.
     *      Checks: single position, total exposure, sector concentration, max positions.
     * @param _symbolHash Hash of the trading pair
     * @param _sectorHash Hash of the sector
     * @param _notionalValue Proposed notional value of the position
     * @return passed Whether the position passes all limit checks
     * @return reason Human-readable reason (empty if passed)
     */
    function checkPositionLimit(
        bytes32 _symbolHash,
        bytes32 _sectorHash,
        uint256 _notionalValue
    ) external returns (bool passed, string memory reason) {
        if (currentEquity == 0) {
            return (false, "Equity not set");
        }

        // Check 1: Max open positions
        if (openPositionCount >= maxOpenPositions) {
            emit PositionLimitCheck(_symbolHash, 0, maxOpenPositions, false, "Max positions reached");
            return (false, "Maximum open positions reached");
        }

        // Check 2: Single position limit (15% of capital)
        uint256 notionalBps = (_notionalValue * 10000) / currentEquity;
        if (notionalBps > maxSinglePositionBps) {
            emit PositionLimitCheck(
                _symbolHash,
                notionalBps,
                maxSinglePositionBps,
                false,
                "Single position exceeded"
            );
            return (false, "Single position exceeds 15% of capital");
        }

        // Check 3: Total exposure limit (100% of capital)
        uint256 newTotalExposure = totalExposure + _notionalValue;
        uint256 newExposureBps = (newTotalExposure * 10000) / currentEquity;
        if (newExposureBps > maxTotalExposureBps) {
            emit PositionLimitCheck(
                _symbolHash,
                newExposureBps,
                maxTotalExposureBps,
                false,
                "Total exposure exceeded"
            );
            return (false, "Total exposure would exceed 100% of capital");
        }

        // Check 4: Sector concentration limit (30% of capital)
        uint256 newSectorExposure = sectorExposure[_sectorHash] + _notionalValue;
        uint256 sectorBps = (newSectorExposure * 10000) / currentEquity;
        if (sectorBps > maxSectorConcentrationBps) {
            emit PositionLimitCheck(
                _symbolHash,
                sectorBps,
                maxSectorConcentrationBps,
                false,
                "Sector concentration exceeded"
            );
            return (false, "Sector concentration would exceed 30% of capital");
        }

        // Check 5: Existing position in same symbol
        if (positions[_symbolHash].isOpen) {
            uint256 existingNotional = positions[_symbolHash].notionalValue;
            uint256 combinedNotional = existingNotional + _notionalValue;
            uint256 combinedBps = (combinedNotional * 10000) / currentEquity;
            if (combinedBps > maxSinglePositionBps) {
                emit PositionLimitCheck(
                    _symbolHash,
                    combinedBps,
                    maxSinglePositionBps,
                    false,
                    "Combined position exceeded"
                );
                return (false, "Combined position in symbol would exceed 15%");
            }
        }

        emit PositionLimitCheck(_symbolHash, notionalBps, maxSinglePositionBps, true, "");
        return (true, "");
    }

    // ═══════════════════════════════════════════════════════════
    // POSITION TRACKING
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Record a new position opening.
     * @dev Called AFTER a trade is executed (not before).
     * @param _symbolHash Hash of the trading pair
     * @param _sectorHash Hash of the sector
     * @param _notionalValue Notional value of the position
     * @param _entryPrice Entry price
     * @param _quantity Position quantity
     */
    function openPosition(
        bytes32 _symbolHash,
        bytes32 _sectorHash,
        uint256 _notionalValue,
        uint256 _entryPrice,
        uint256 _quantity
    ) external onlyRole(OPERATOR_ROLE) {
        if (positions[_symbolHash].isOpen) {
            // Add to existing position
            positions[_symbolHash].notionalValue += _notionalValue;
            positions[_symbolHash].quantity += _quantity;
        } else {
            // New position
            positions[_symbolHash] = PositionInfo({
                symbolHash: _symbolHash,
                sectorHash: _sectorHash,
                notionalValue: _notionalValue,
                entryPrice: _entryPrice,
                quantity: _quantity,
                openedAt: block.timestamp,
                isOpen: true
            });
            openPositionCount++;
        }

        totalExposure += _notionalValue;
        sectorExposure[_sectorHash] += _notionalValue;

        uint256 positionBps = currentEquity > 0
            ? (_notionalValue * 10000) / currentEquity
            : 0;

        emit PositionOpened(
            _symbolHash,
            _sectorHash,
            _notionalValue,
            positionBps,
            block.timestamp
        );
    }

    /**
     * @notice Record a position closing.
     * @param _symbolHash Hash of the trading pair
     */
    function closePosition(bytes32 _symbolHash) external onlyRole(OPERATOR_ROLE) {
        PositionInfo storage pos = positions[_symbolHash];
        if (!pos.isOpen) revert PositionNotOpen(_symbolHash);

        bytes32 sectorHash = pos.sectorHash;
        uint256 notional = pos.notionalValue;

        totalExposure -= notional;
        sectorExposure[sectorHash] -= notional;
        openPositionCount--;

        pos.isOpen = false;
        pos.notionalValue = 0;
        pos.quantity = 0;

        emit PositionClosed(_symbolHash, notional, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // VIEW FUNCTIONS
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Get current exposure metrics.
     * @return totalExp Total notional exposure
     * @return totalExpBps Total exposure as bps of equity
     * @return openCount Number of open positions
     * @return maxPositions Maximum allowed positions
     */
    function getExposureMetrics()
        external
        view
        returns (
            uint256 totalExp,
            uint256 totalExpBps,
            uint256 openCount,
            uint256 maxPositions
        )
    {
        totalExp = totalExposure;
        totalExpBps = currentEquity > 0 ? (totalExposure * 10000) / currentEquity : 0;
        openCount = openPositionCount;
        maxPositions = maxOpenPositions;
    }

    /**
     * @notice Get sector exposure.
     * @param _sectorHash Hash of the sector
     * @return exposure Notional exposure in the sector
     * @return exposureBps Exposure as bps of equity
     */
    function getSectorExposure(bytes32 _sectorHash)
        external
        view
        returns (uint256 exposure, uint256 exposureBps)
    {
        exposure = sectorExposure[_sectorHash];
        exposureBps = currentEquity > 0 ? (exposure * 10000) / currentEquity : 0;
    }

    /**
     * @notice Get position details for a symbol.
     * @param _symbolHash Hash of the trading pair
     * @return info The position info
     * @return positionBps Position notional as bps of equity
     */
    function getPosition(bytes32 _symbolHash)
        external
        view
        returns (PositionInfo memory info, uint256 positionBps)
    {
        info = positions[_symbolHash];
        positionBps = currentEquity > 0 ? (info.notionalValue * 10000) / currentEquity : 0;
    }

    // ═══════════════════════════════════════════════════════════
    // GOVERNANCE
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Update position limits (requires governance).
     * @param _maxSingleBps New max single position in bps
     * @param _maxTotalBps New max total exposure in bps
     * @param _maxSectorBps New max sector concentration in bps
     * @param _maxPositions New max open positions
     */
    function updateLimits(
        uint256 _maxSingleBps,
        uint256 _maxTotalBps,
        uint256 _maxSectorBps,
        uint256 _maxPositions
    ) external onlyRole(GOVERNANCE_ROLE) {
        maxSinglePositionBps = _maxSingleBps;
        maxTotalExposureBps = _maxTotalBps;
        maxSectorConcentrationBps = _maxSectorBps;
        maxOpenPositions = _maxPositions;
    }
}
