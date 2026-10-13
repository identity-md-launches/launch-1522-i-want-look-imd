// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title IMDChadBoard
/// @notice Immutable, atomically published rankings of wallets associated with activated IMD seats.
/// @dev Historical observations are attestations by an owner-appointed indexer, NOT trustless proofs.
///      The contract validates accounting and computes scores; it cannot read historical EVM logs.
contract IMDChadBoard {
    uint256 public constant MAX_TOKENS = 16;
    uint256 public constant MAX_BATCH = 20;
    uint256 public constant MAX_PAGE = 100;
    uint256 public constant CLAIM_WINDOW = 30 days;
    uint256 private constant BPS = 10_000;

    enum Status {
        None,
        Building,
        Published,
        Aborted
    }

    enum Tier {
        Observer,
        Contributor,
        Chad,
        GigaChad
    }

    struct TokenPolicy {
        address token;
        uint128 supportTarget; // Native token units; never assumes 18 decimals.
    }

    struct WalletMetrics {
        uint32 activeSeats;
        uint32 launches;
        uint32 eligibleClaims; // Distinct reward allocations, including still-unclaimed allocations.
        uint32 claimedClaims; // Allocations with at least one nonzero claim, counted once each.
        uint64 totalClaimDelay; // Sum over claimed allocations of min(first-claim delay, CLAIM_WINDOW), in seconds.
        uint64 maxClaimDelay; // Largest capped first-claim delay; never above CLAIM_WINDOW.
        uint32 interactions; // Successful, recognized on-chain app interactions.
        uint16 distinctApps;
    }

    struct TokenReport {
        uint128 claimed;
        uint128 bought;
        uint128 sold;
        uint128 otherOut;
        uint128 rewardHeld;
        uint128 rewardSold;
        uint128 rewardOtherOut;
        uint128 balance;
    }

    struct WalletReport {
        address wallet;
        WalletMetrics metrics;
        TokenReport[] tokens; // Exactly the epoch's token-policy order.
    }

    struct WalletStats {
        WalletMetrics metrics;
        uint32 rank; // Unique, one-based; zero means absent from this snapshot.
        uint16 score; // 0..10,000.
        uint16 retentionBps;
        uint16 supportBps;
    }

    struct SnapshotInput {
        uint64 blockNumber;
        uint64 timestamp;
        bytes32 blockHash;
        uint64 totalSeats;
        uint64 activatedSeats;
        uint32 walletCount;
        bytes32 evidenceHash; // SHA-256 of the retained canonical indexer report.
        uint64 configuration; // Expected configuration; rejects preparation/configuration races.
    }

    struct Epoch {
        Status status;
        SnapshotInput snapshot;
        uint64 configuration;
        uint64 maxAge;
        uint64 publishedAt;
        uint64 seatsWritten;
        uint32 walletsWritten;
        address reporter;
        address seatNFT;
        bytes32 methodologyHash;
    }

    struct Leader {
        address wallet;
        uint32 rank;
        uint16 score;
        Tier tier;
        uint32 activeSeats;
    }

    struct Rating {
        uint64 epoch;
        uint64 asOfBlock;
        uint64 asOfTimestamp;
        bool stale;
        bool currentConfiguration;
        bool found;
        Tier tier;
        WalletStats stats;
    }

    error Unauthorized();
    error InvalidAddress();
    error NotConfigured();
    error InvalidConfiguration();
    error PendingEpoch();
    error InvalidEpoch();
    error InvalidSnapshot();
    error SnapshotTooOld();
    error BlockHashMismatch();
    error InvalidBatch();
    error InvalidWallet();
    error InvalidMetrics();
    error InvalidTokenReport();
    error DuplicateWallet();
    error InvalidOrder();
    error IncompleteSnapshot();
    error InvalidPage();
    error NoPublishedEpoch();

    event OwnershipTransferStarted(address indexed owner, address indexed pendingOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed owner);
    event ReporterSet(address indexed reporter, uint64 configuration);
    event SourcesSet(address indexed seatNFT, bytes32 methodologyHash, uint64 configuration);
    event TokenPoliciesSet(bytes32 policiesHash, uint64 configuration);
    event MaxAgeSet(uint64 maxAge, uint64 configuration);
    event EpochStarted(uint64 indexed epoch, uint64 indexed asOfBlock, bytes32 evidenceHash, uint64 configuration);
    event WalletAppended(uint64 indexed epoch, address indexed wallet, uint32 rank, uint16 score);
    event EpochPublished(uint64 indexed epoch, uint32 wallets, uint64 activatedSeats);
    event EpochAborted(uint64 indexed epoch);

    address public owner;
    address public pendingOwner;
    address public reporter;
    address public seatNFT;
    bytes32 public methodologyHash;
    uint64 public maxAge = 2 days;
    uint64 public configuration;
    uint64 public epochCount;
    uint64 public pendingEpoch;
    uint64 public latestEpoch;

    TokenPolicy[] private _tokenPolicies;
    mapping(uint64 => Epoch) private _epochs;
    mapping(uint64 => TokenPolicy[]) private _epochTokens;
    mapping(uint64 => address[]) private _ranking;
    mapping(uint64 => mapping(address => WalletStats)) private _wallets;
    mapping(uint64 => mapping(address => TokenReport[])) private _portfolios;

    /// @param initialOwner The launch owner's address, supplied explicitly by the deployment factory.
    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert InvalidAddress();
        owner = initialOwner;
        emit OwnershipTransferred(address(0), initialOwner);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyReporter() {
        if (reporter == address(0)) revert NotConfigured();
        if (msg.sender != reporter) revert Unauthorized();
        _;
    }

    modifier noPendingEpoch() {
        if (pendingEpoch != 0) revert PendingEpoch();
        _;
    }

    function transferOwnership(address nextOwner) external onlyOwner {
        if (nextOwner == address(0)) revert InvalidAddress();
        pendingOwner = nextOwner;
        emit OwnershipTransferStarted(owner, nextOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert Unauthorized();
        address previous = owner;
        owner = msg.sender;
        pendingOwner = address(0);
        emit OwnershipTransferred(previous, msg.sender);
    }

    /// @notice Revoke with address(0). Any unfinished draft is aborted in the same transaction, so a reporter
    ///         that keeps re-opening drafts cannot veto its own revocation or rotation.
    function setReporter(address nextReporter) external onlyOwner {
        uint64 pending = pendingEpoch;
        if (pending != 0) {
            _epochs[pending].status = Status.Aborted;
            pendingEpoch = 0;
            emit EpochAborted(pending);
        }
        reporter = nextReporter;
        emit ReporterSet(nextReporter, ++configuration);
    }

    /// @notice Hash binds the complete indexing policy, including ABI schemas, start block and allowlists.
    function setSources(address nft, bytes32 policyHash) external onlyOwner noPendingEpoch {
        if (nft == address(0)) revert InvalidAddress();
        if (policyHash == bytes32(0)) revert InvalidConfiguration();
        seatNFT = nft;
        methodologyHash = policyHash;
        emit SourcesSet(nft, policyHash, ++configuration);
    }

    function setTokenPolicies(TokenPolicy[] calldata policies) external onlyOwner noPendingEpoch {
        if (policies.length == 0 || policies.length > MAX_TOKENS) revert InvalidConfiguration();
        delete _tokenPolicies;
        address previous;
        for (uint256 i; i < policies.length; ++i) {
            TokenPolicy calldata p = policies[i];
            if (p.token <= previous || p.supportTarget == 0) revert InvalidConfiguration();
            _tokenPolicies.push(p);
            previous = p.token;
        }
        emit TokenPoliciesSet(keccak256(abi.encode(policies)), ++configuration);
    }

    function setMaxAge(uint64 seconds_) external onlyOwner noPendingEpoch {
        if (seconds_ < 1 hours || seconds_ > 30 days) revert InvalidConfiguration();
        maxAge = seconds_;
        emit MaxAgeSet(seconds_, ++configuration);
    }

    function tokenPolicies() external view returns (TokenPolicy[] memory) {
        return _tokenPolicies;
    }

    /// @notice Begin a complete census. The reporter must use a finalized Ethereum block.
    /// @dev Recent hashes are independently checked; older hashes and all observations rely on the reporter.
    function beginEpoch(SnapshotInput calldata snapshot) external onlyReporter noPendingEpoch returns (uint64 id) {
        if (seatNFT.code.length == 0 || methodologyHash == bytes32(0) || _tokenPolicies.length == 0) {
            revert NotConfigured();
        }
        for (uint256 i; i < _tokenPolicies.length; ++i) {
            if (_tokenPolicies[i].token.code.length == 0) revert NotConfigured();
        }
        if (snapshot.configuration != configuration) revert InvalidConfiguration();
        if (
            snapshot.blockNumber == 0 || snapshot.blockNumber >= block.number || snapshot.timestamp == 0
                || snapshot.timestamp > block.timestamp || snapshot.blockHash == bytes32(0)
                || snapshot.evidenceHash == bytes32(0) || snapshot.activatedSeats > snapshot.totalSeats
                || snapshot.walletCount > snapshot.activatedSeats
                || (snapshot.walletCount == 0 && snapshot.activatedSeats != 0)
        ) revert InvalidSnapshot();
        if (block.timestamp - snapshot.timestamp > maxAge) revert SnapshotTooOld();
        if (block.number - snapshot.blockNumber <= 256 && blockhash(snapshot.blockNumber) != snapshot.blockHash) {
            revert BlockHashMismatch();
        }
        if (latestEpoch != 0) {
            SnapshotInput storage last = _epochs[latestEpoch].snapshot;
            if (snapshot.blockNumber <= last.blockNumber || snapshot.timestamp <= last.timestamp) {
                revert InvalidSnapshot();
            }
        }
        id = ++epochCount;
        pendingEpoch = id;
        Epoch storage epoch = _epochs[id];
        epoch.status = Status.Building;
        epoch.snapshot = snapshot;
        epoch.configuration = configuration;
        epoch.maxAge = maxAge;
        epoch.reporter = msg.sender;
        epoch.seatNFT = seatNFT;
        epoch.methodologyHash = methodologyHash;
        for (uint256 i; i < _tokenPolicies.length; ++i) {
            _epochTokens[id].push(_tokenPolicies[i]);
        }
        emit EpochStarted(id, snapshot.blockNumber, snapshot.evidenceHash, configuration);
    }

    /// @notice Supply rows sorted by descending computed score, then ascending numeric wallet address.
    /// @dev Ordering and duplicates are checked across batches as well as within each batch.
    function appendWallets(uint64 id, WalletReport[] calldata reports) external onlyReporter {
        Epoch storage epoch = _building(id);
        uint256 length = reports.length;
        if (length == 0 || length > MAX_BATCH || uint256(epoch.walletsWritten) + length > epoch.snapshot.walletCount) {
            revert InvalidBatch();
        }
        for (uint256 i; i < length; ++i) {
            WalletReport calldata report = reports[i];
            if (report.wallet == address(0) || report.metrics.activeSeats == 0) revert InvalidWallet();
            if (_wallets[id][report.wallet].rank != 0) revert DuplicateWallet();
            (uint16 score, uint16 retention, uint16 support) =
                _validateAndScore(report.metrics, report.tokens, _epochTokens[id]);
            if (report.metrics.maxClaimDelay > epoch.snapshot.timestamp) revert InvalidMetrics();
            uint32 written = epoch.walletsWritten;
            if (written > 0) {
                address previous = _ranking[id][written - 1];
                uint16 previousScore = _wallets[id][previous].score;
                if (score > previousScore || (score == previousScore && report.wallet <= previous)) {
                    revert InvalidOrder();
                }
            }
            epoch.seatsWritten += report.metrics.activeSeats;
            if (epoch.seatsWritten > epoch.snapshot.activatedSeats) revert InvalidSnapshot();
            uint32 rank = ++epoch.walletsWritten;
            _wallets[id][report.wallet] = WalletStats(report.metrics, rank, score, retention, support);
            _ranking[id].push(report.wallet);
            for (uint256 j; j < report.tokens.length; ++j) {
                _portfolios[id][report.wallet].push(report.tokens[j]);
            }
            emit WalletAppended(id, report.wallet, rank, score);
        }
    }

    /// @notice A draft never affects public rankings. Publish only a complete census with matching seat totals.
    function finalizeEpoch(uint64 id) external onlyReporter {
        Epoch storage epoch = _building(id);
        if (epoch.walletsWritten != epoch.snapshot.walletCount || epoch.seatsWritten != epoch.snapshot.activatedSeats) {
            revert IncompleteSnapshot();
        }
        if (block.timestamp - epoch.snapshot.timestamp > epoch.maxAge) revert SnapshotTooOld();
        epoch.status = Status.Published;
        epoch.publishedAt = uint64(block.timestamp);
        latestEpoch = id;
        pendingEpoch = 0;
        emit EpochPublished(id, epoch.walletsWritten, epoch.seatsWritten);
    }

    /// @notice Owner can abandon a stalled or compromised reporter's draft; published history is immutable.
    function abortEpoch(uint64 id) external {
        if (msg.sender != owner && (reporter == address(0) || msg.sender != reporter)) revert Unauthorized();
        Epoch storage epoch = _building(id);
        epoch.status = Status.Aborted;
        pendingEpoch = 0;
        emit EpochAborted(id);
    }

    function getEpoch(uint64 id) external view returns (Epoch memory) {
        if (_epochs[id].status == Status.None) revert InvalidEpoch();
        return _epochs[id];
    }

    function epochTokenPolicies(uint64 id) external view returns (TokenPolicy[] memory) {
        _published(id);
        return _epochTokens[id];
    }

    function summary() external view returns (Epoch memory epoch, bool stale, bool currentConfiguration) {
        if (latestEpoch == 0) revert NoPublishedEpoch();
        epoch = _epochs[latestEpoch];
        currentConfiguration = epoch.configuration == configuration;
        stale = block.timestamp - epoch.snapshot.timestamp > epoch.maxAge || !currentConfiguration;
    }

    function walletRating(address wallet) external view returns (Rating memory) {
        if (latestEpoch == 0) revert NoPublishedEpoch();
        return walletAt(latestEpoch, wallet);
    }

    function walletAt(uint64 id, address wallet) public view returns (Rating memory rating) {
        Epoch storage epoch = _published(id);
        rating.epoch = id;
        rating.asOfBlock = epoch.snapshot.blockNumber;
        rating.asOfTimestamp = epoch.snapshot.timestamp;
        rating.currentConfiguration = epoch.configuration == configuration;
        rating.stale = block.timestamp - epoch.snapshot.timestamp > epoch.maxAge || !rating.currentConfiguration;
        rating.stats = _wallets[id][wallet];
        rating.found = rating.stats.rank != 0;
        rating.tier = tierFor(rating.stats.score);
    }

    function walletTokens(uint64 id, address wallet) external view returns (TokenReport[] memory) {
        _published(id);
        return _portfolios[id][wallet];
    }

    /// @notice O(limit) query; total rank is stored, so callers do not have to scan all wallets.
    function leaderboard(uint64 id, uint32 offset, uint32 limit) external view returns (Leader[] memory page) {
        Epoch storage epoch = _published(id);
        if (limit == 0 || limit > MAX_PAGE) revert InvalidPage();
        uint256 count = epoch.walletsWritten;
        if (offset >= count) return new Leader[](0);
        uint256 length = count - offset;
        if (length > limit) length = limit;
        page = new Leader[](length);
        for (uint256 i; i < length; ++i) {
            address wallet = _ranking[id][uint256(offset) + i];
            WalletStats storage stats = _wallets[id][wallet];
            page[i] = Leader(wallet, stats.rank, stats.score, tierFor(stats.score), stats.metrics.activeSeats);
        }
    }

    /// @notice Preview against current policies before sorting a complete report for publication.
    function previewScore(WalletMetrics calldata metrics, TokenReport[] calldata tokens)
        external
        view
        returns (uint16 score, uint16 retentionBps, uint16 supportBps)
    {
        if (_tokenPolicies.length == 0) revert NotConfigured();
        return _validateAndScore(metrics, tokens, _tokenPolicies);
    }

    function tierFor(uint16 score) public pure returns (Tier) {
        if (score >= 7500) return Tier.GigaChad;
        if (score >= 5000) return Tier.Chad;
        if (score >= 2500) return Tier.Contributor;
        return Tier.Observer;
    }

    function _building(uint64 id) private view returns (Epoch storage epoch) {
        if (id == 0 || id != pendingEpoch) revert InvalidEpoch();
        epoch = _epochs[id];
        if (epoch.status != Status.Building) revert InvalidEpoch();
    }

    function _published(uint64 id) private view returns (Epoch storage epoch) {
        epoch = _epochs[id];
        if (epoch.status != Status.Published) revert InvalidEpoch();
    }

    function _validateAndScore(
        WalletMetrics calldata metrics,
        TokenReport[] calldata tokens,
        TokenPolicy[] storage policies
    ) private view returns (uint16 score, uint16 retentionBps, uint16 supportBps) {
        uint256 claims = metrics.claimedClaims;
        // Each claim's delay is capped at CLAIM_WINDOW before it is summed, so one late claim can never
        // outweigh the completion credit it earns: an extra claim adds a nonnegative term below.
        if (
            metrics.activeSeats == 0 || claims > metrics.eligibleClaims || metrics.distinctApps > metrics.interactions
                || (claims == 0 && (metrics.totalClaimDelay != 0 || metrics.maxClaimDelay != 0))
                || metrics.maxClaimDelay > CLAIM_WINDOW || metrics.totalClaimDelay < metrics.maxClaimDelay
                || metrics.totalClaimDelay > claims * metrics.maxClaimDelay
        ) revert InvalidMetrics();
        if (tokens.length != policies.length) revert InvalidTokenReport();
        uint256 retentionWeight;
        uint256 retentionSum;
        uint256 supportSum;
        for (uint256 i; i < tokens.length; ++i) {
            TokenReport calldata token = tokens[i];
            if (
                uint256(token.rewardHeld) + token.rewardSold + token.rewardOtherOut != token.claimed
                    || token.rewardHeld > token.balance || token.rewardSold > token.sold
                    || token.rewardOtherOut > token.otherOut
            ) revert InvalidTokenReport();
            uint256 target = policies[i].supportTarget;
            if (token.claimed != 0) {
                // Weight each token's ratio by its claimed size relative to the token's support target,
                // so a dust claim held in one token cannot offset rewards sold in another. The weight is
                // at least 1 for any nonzero claim because supportTarget < 2**128.
                uint256 weight = (_min(token.claimed, target) << 128) / target;
                retentionWeight += weight;
                retentionSum += weight * (uint256(token.rewardHeld) * BPS / token.claimed);
            }
            supportSum += _min(token.bought, target) * BPS / target;
        }
        if ((claims == 0) != (retentionWeight == 0)) revert InvalidMetrics();
        retentionBps = retentionWeight == 0 ? 0 : uint16(retentionSum / retentionWeight);
        supportBps = uint16(supportSum / policies.length);
        uint256 claimPoints;
        if (claims != 0) {
            claimPoints =
                1500 * (CLAIM_WINDOW * claims - metrics.totalClaimDelay) / (CLAIM_WINDOW * metrics.eligibleClaims);
        }
        score = uint16(
            _min(metrics.launches, 30) * 100 + claimPoints + uint256(retentionBps) * 3000 / BPS + uint256(supportBps)
                * 1500 / BPS + _min(metrics.distinctApps, 10) * 100
        );
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
