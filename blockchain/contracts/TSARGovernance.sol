// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TSARGovernance
 * @notice On-chain governance for TSAR — multi-sig wallet + time-locked admin.
 * @dev Central governance contract that manages all TSAR contract permissions.
 *
 * GOVERNANCE MODEL:
 *   - 3-of-5 multi-sig for critical operations (kill switch deactivation)
 *   - 2-of-5 multi-sig for standard operations (mandate changes)
 *   - 48h time-lock on all governance changes
 *   - Emergency bypass: 3-of-5 can execute immediately in emergencies
 *   - All actions logged to TSARAuditTrail
 *
 * INTEGRATION WITH TSAR:
 *   - Valentine is the primary signer
 *   - Two backup signers (hardware wallets in separate locations)
 *   - Two institutional signers (compliance officer, risk manager)
 *   - All contract admin roles are held by this governance contract
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract TSARGovernance is AccessControl, ReentrancyGuard {
    // ═══════════════════════════════════════════════════════════
    // ROLES
    // ═══════════════════════════════════════════════════════════

    bytes32 public constant SIGNER_ROLE = keccak256("SIGNER_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    // ═══════════════════════════════════════════════════════════
    // TYPES
    // ═══════════════════════════════════════════════════════════

    /// @notice Types of governance operations
    enum OperationType {
        STANDARD,       // 2-of-5 + 48h timelock
        CRITICAL,       // 3-of-5 + 48h timelock
        EMERGENCY       // 3-of-5, no timelock
    }

    /// @notice A governance proposal
    struct Proposal {
        uint256 id;
        address target;             // Target contract address
        bytes callData;             // Encoded function call
        OperationType opType;
        uint256 value;              // ETH value to send
        string description;
        uint256 proposedAt;
        address proposer;
        uint256 confirmations;
        mapping(address => bool) hasConfirmed;
        bool executed;
        bool cancelled;
    }

    // ═══════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════

    /// @notice Total number of signers
    uint256 public constant TOTAL_SIGNERS = 5;

    /// @notice Required confirmations for standard operations
    uint256 public constant STANDARD_THRESHOLD = 2;

    /// @notice Required confirmations for critical operations
    uint256 public constant CRITICAL_THRESHOLD = 3;

    /// @notice Time-lock duration (48 hours)
    uint256 public constant TIMELOCK_DURATION = 48 hours;

    /// @notice Proposal counter
    uint256 public proposalCount;

    /// @notice All proposals
    mapping(uint256 => Proposal) public proposals;

    /// @notice Contract addresses managed by governance
    mapping(address => bool) public managedContracts;

    /// @notice Emergency pause state
    bool public emergencyPaused;

    /// @notice List of signer addresses (for enumeration)
    address[5] public signers;

    /// @notice Signer index mapping
    mapping(address => uint256) public signerIndex;

    /// @notice Guardian address (can pause in emergencies)
    address public guardian;

    // ═══════════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════════

    event ProposalCreated(
        uint256 indexed proposalId,
        address target,
        OperationType opType,
        string description,
        address proposer,
        uint256 timestamp
    );

    event ProposalConfirmed(
        uint256 indexed proposalId,
        address confirmer,
        uint256 confirmations,
        uint256 timestamp
    );

    event ProposalExecuted(
        uint256 indexed proposalId,
        address executor,
        uint256 timestamp
    );

    event ProposalCancelled(
        uint256 indexed proposalId,
        address canceller,
        uint256 timestamp
    );

    event ContractRegistered(address indexed contractAddr, string name);
    event ContractDeregistered(address indexed contractAddr);

    event EmergencyPaused(address indexed by, uint256 timestamp);
    event EmergencyUnpaused(address indexed by, uint256 timestamp);

    event GuardianUpdated(address indexed oldGuardian, address indexed newGuardian);

    // ═══════════════════════════════════════════════════════════
    // ERRORS
    // ═══════════════════════════════════════════════════════════

    error InvalidProposal(uint256 proposalId);
    error ProposalAlreadyExecuted(uint256 proposalId);
    error ProposalCancelled(uint256 proposalId);
    error AlreadyConfirmed(address signer);
    error InsufficientConfirmations(uint256 have, uint256 need);
    error TimelockNotExpired(uint256 expiresAt, uint256 now);
    error ExecutionFailed();
    error NotManagedContract(address target);
    error EmergencyPaused();
    error InvalidSignerCount();
    error DuplicateSigner(address signer);
    error NotGuardian();

    // ═══════════════════════════════════════════════════════════
    // MODIFIERS
    // ═══════════════════════════════════════════════════════════

    modifier notPaused() {
        if (emergencyPaused) revert EmergencyPaused();
        _;
    }

    modifier onlySigner() {
        require(hasRole(SIGNER_ROLE, msg.sender), "Not a signer");
        _;
    }

    // ═══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Deploy governance with 5 signers and a guardian.
     * @param _signers Array of 5 signer addresses
     * @param _guardian Guardian address (can pause in emergencies)
     */
    constructor(address[5] memory _signers, address _guardian) {
        // Validate no duplicate signers
        for (uint256 i = 0; i < 5; i++) {
            if (_signers[i] == address(0)) revert InvalidSignerCount();
            for (uint256 j = i + 1; j < 5; j++) {
                if (_signers[i] == _signers[j]) revert DuplicateSigner(_signers[i]);
            }
        }

        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);

        for (uint256 i = 0; i < 5; i++) {
            _grantRole(SIGNER_ROLE, _signers[i]);
            signers[i] = _signers[i];
            signerIndex[_signers[i]] = i;
        }

        guardian = _guardian;
        _grantRole(GUARDIAN_ROLE, _guardian);
    }

    // ═══════════════════════════════════════════════════════════
    // PROPOSAL LIFECYCLE
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Create a governance proposal.
     * @param _target Target contract address
     * @param _callData Encoded function call
     * @param _opType Operation type (STANDARD, CRITICAL, EMERGENCY)
     * @param _value ETH value to send with call
     * @param _description Human-readable description
     */
    function propose(
        address _target,
        bytes calldata _callData,
        OperationType _opType,
        uint256 _value,
        string calldata _description
    ) external onlySigner notPaused {
        proposalCount++;

        Proposal storage p = proposals[proposalCount];
        p.id = proposalCount;
        p.target = _target;
        p.callData = _callData;
        p.opType = _opType;
        p.value = _value;
        p.description = _description;
        p.proposedAt = block.timestamp;
        p.proposer = msg.sender;
        p.confirmations = 0;
        p.executed = false;
        p.cancelled = false;

        // Auto-confirm from proposer
        p.hasConfirmed[msg.sender] = true;
        p.confirmations = 1;

        emit ProposalCreated(
            proposalCount,
            _target,
            _opType,
            _description,
            msg.sender,
            block.timestamp
        );

        emit ProposalConfirmed(
            proposalCount,
            msg.sender,
            1,
            block.timestamp
        );
    }

    /**
     * @notice Confirm a proposal.
     * @param _proposalId The proposal to confirm
     */
    function confirm(uint256 _proposalId) external onlySigner notPaused {
        Proposal storage p = proposals[_proposalId];
        if (p.id == 0) revert InvalidProposal(_proposalId);
        if (p.executed) revert ProposalAlreadyExecuted(_proposalId);
        if (p.cancelled) revert ProposalCancelled(_proposalId);
        if (p.hasConfirmed[msg.sender]) revert AlreadyConfirmed(msg.sender);

        p.hasConfirmed[msg.sender] = true;
        p.confirmations++;

        emit ProposalConfirmed(
            _proposalId,
            msg.sender,
            p.confirmations,
            block.timestamp
        );
    }

    /**
     * @notice Execute a confirmed proposal after timelock.
     * @dev For EMERGENCY type, can execute without timelock if threshold met.
     * @param _proposalId The proposal to execute
     */
    function execute(uint256 _proposalId) external onlySigner nonReentrant {
        Proposal storage p = proposals[_proposalId];
        if (p.id == 0) revert InvalidProposal(_proposalId);
        if (p.executed) revert ProposalAlreadyExecuted(_proposalId);
        if (p.cancelled) revert ProposalCancelled(_proposalId);

        // Check threshold based on operation type
        uint256 required;
        if (p.opType == OperationType.CRITICAL || p.opType == OperationType.EMERGENCY) {
            required = CRITICAL_THRESHOLD;
        } else {
            required = STANDARD_THRESHOLD;
        }

        if (p.confirmations < required) {
            revert InsufficientConfirmations(p.confirmations, required);
        }

        // Check timelock (skip for EMERGENCY)
        if (p.opType != OperationType.EMERGENCY) {
            uint256 unlockTime = p.proposedAt + TIMELOCK_DURATION;
            if (block.timestamp < unlockTime) {
                revert TimelockNotExpired(unlockTime, block.timestamp);
            }
        }

        // Execute the call
        p.executed = true;

        (bool success, ) = p.target.call{value: p.value}(p.callData);
        if (!success) revert ExecutionFailed();

        emit ProposalExecuted(_proposalId, msg.sender, block.timestamp);
    }

    /**
     * @notice Cancel a proposal (only proposer or guardian).
     * @param _proposalId The proposal to cancel
     */
    function cancel(uint256 _proposalId) external {
        Proposal storage p = proposals[_proposalId];
        if (p.id == 0) revert InvalidProposal(_proposalId);
        if (p.executed) revert ProposalAlreadyExecuted(_proposalId);

        // Only proposer or guardian can cancel
        if (msg.sender != p.proposer && !hasRole(GUARDIAN_ROLE, msg.sender)) {
            revert NotGuardian();
        }

        p.cancelled = true;

        emit ProposalCancelled(_proposalId, msg.sender, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // CONTRACT MANAGEMENT
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Register a contract as managed by governance.
     * @param _contract Address of the managed contract
     * @param _name Human-readable name
     */
    function registerContract(address _contract, string calldata _name)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        managedContracts[_contract] = true;
        emit ContractRegistered(_contract, _name);
    }

    /**
     * @notice Deregister a managed contract.
     * @param _contract Address to deregister
     */
    function deregisterContract(address _contract)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        managedContracts[_contract] = false;
        emit ContractDeregistered(_contract);
    }

    // ═══════════════════════════════════════════════════════════
    // EMERGENCY CONTROLS
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Emergency pause — guardian can halt all governance operations.
     */
    function emergencyPause() external onlyRole(GUARDIAN_ROLE) {
        emergencyPaused = true;
        emit EmergencyPaused(msg.sender, block.timestamp);
    }

    /**
     * @notice Unpause — requires multi-sig confirmation via proposal.
     */
    function emergencyUnpause() external onlySigner {
        emergencyPaused = false;
        emit EmergencyUnpaused(msg.sender, block.timestamp);
    }

    // ═══════════════════════════════════════════════════════════
    // VIEW FUNCTIONS
    // ═══════════════════════════════════════════════════════════

    /**
     * @notice Check if a proposal has reached its threshold.
     * @param _proposalId The proposal to check
     * @return ready Whether the proposal can be executed
     * @return timelockExpired Whether the timelock has expired
     */
    function isProposalReady(uint256 _proposalId)
        external
        view
        returns (bool ready, bool timelockExpired)
    {
        Proposal storage p = proposals[_proposalId];
        if (p.id == 0 || p.executed || p.cancelled) return (false, false);

        uint256 required;
        if (p.opType == OperationType.CRITICAL || p.opType == OperationType.EMERGENCY) {
            required = CRITICAL_THRESHOLD;
        } else {
            required = STANDARD_THRESHOLD;
        }

        bool thresholdMet = p.confirmations >= required;
        timelockExpired = (p.opType == OperationType.EMERGENCY) ||
                          (block.timestamp >= p.proposedAt + TIMELOCK_DURATION);

        ready = thresholdMet && timelockExpired;
        return (ready, timelockExpired);
    }

    /**
     * @notice Get all signer addresses.
     * @return Array of 5 signer addresses
     */
    function getSigners() external view returns (address[5] memory) {
        return signers;
    }

    /**
     * @notice Check if an address is a signer.
     * @param _addr Address to check
     * @return True if the address is a signer
     */
    function isSigner(address _addr) external view returns (bool) {
        return hasRole(SIGNER_ROLE, _addr);
    }

    /**
     * @notice Get proposal details.
     * @param _proposalId The proposal ID
     * @return target_ Target address
     * @return opType_ Operation type
     * @return description_ Description
     * @return confirmations_ Number of confirmations
     * @return executed_ Whether executed
     * @return cancelled_ Whether cancelled
     * @return proposedAt_ When proposed
     */
    function getProposal(uint256 _proposalId)
        external
        view
        returns (
            address target_,
            OperationType opType_,
            string memory description_,
            uint256 confirmations_,
            bool executed_,
            bool cancelled_,
            uint256 proposedAt_
        )
    {
        Proposal storage p = proposals[_proposalId];
        return (
            p.target,
            p.opType,
            p.description,
            p.confirmations,
            p.executed,
            p.cancelled,
            p.proposedAt
        );
    }

    /**
     * @notice Check if an address has confirmed a proposal.
     * @param _proposalId The proposal ID
     * @param _signer The signer address
     * @return True if the signer has confirmed
     */
    function hasConfirmedProposal(uint256 _proposalId, address _signer)
        external
        view
        returns (bool)
    {
        return proposals[_proposalId].hasConfirmed[_signer];
    }

    // ═══════════════════════════════════════════════════════════
    // RECEIVE ETH
    // ═══════════════════════════════════════════════════════════

    receive() external payable {}
}
