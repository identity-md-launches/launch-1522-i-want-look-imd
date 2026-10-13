// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {IMDChadBoard as Board} from "../src/IMDChadBoard.sol";

contract BoardFixture is Test {
    Board internal board;
    address internal owner = makeAddr("owner");
    address internal reporter = makeAddr("reporter");
    address internal stranger = makeAddr("stranger");
    address internal nft = address(0x1000);
    address internal token = address(0x2000);
    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);
    bytes32 internal constant POLICY = keccak256("reviewed indexing methodology");

    function setUp() public virtual {
        vm.warp(100 days);
        vm.roll(1000);
        vm.etch(nft, hex"00");
        vm.etch(token, hex"00");
        // Constructor caller is deliberately NOT the nominated owner.
        vm.prank(stranger);
        board = new Board(owner);
        vm.startPrank(owner);
        board.setSources(nft, POLICY);
        board.setReporter(reporter);
        board.setTokenPolicies(_policies());
        vm.stopPrank();
    }

    function _policies() internal view returns (Board.TokenPolicy[] memory policies) {
        policies = new Board.TokenPolicy[](1);
        policies[0] = Board.TokenPolicy(token, 100e6);
    }

    function _input(uint32 count, uint64 seats) internal returns (Board.SnapshotInput memory input) {
        uint64 height = uint64(vm.getBlockNumber() - 50);
        bytes32 hash = keccak256(abi.encode(height));
        vm.setBlockhash(height, hash);
        input = Board.SnapshotInput(
            height,
            uint64(vm.getBlockTimestamp() - 1 hours),
            hash,
            seats + 5,
            seats,
            count,
            POLICY,
            board.configuration()
        );
    }

    function _begin(uint32 count, uint64 seats) internal returns (uint64) {
        Board.SnapshotInput memory input = _input(count, seats);
        vm.prank(reporter);
        return board.beginEpoch(input);
    }

    function _report(address wallet, uint32 seats, uint32 launches)
        internal
        pure
        returns (Board.WalletReport memory r)
    {
        r.wallet = wallet;
        r.metrics = Board.WalletMetrics(seats, launches, 1, 1, 1 days, 1 days, 2, 2);
        r.tokens = new Board.TokenReport[](1);
        r.tokens[0] = Board.TokenReport(100e6, 50e6, 0, 0, 100e6, 0, 0, 150e6);
    }

    function _append(uint64 id, Board.WalletReport memory report) internal {
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = report;
        vm.prank(reporter);
        board.appendWallets(id, reports);
    }

    function _publishOne() internal returns (uint64 id) {
        id = _begin(1, 2);
        _append(id, _report(alice, 2, 10));
        vm.prank(reporter);
        board.finalizeEpoch(id);
    }
}

contract IMDChadBoardTest is BoardFixture {
    function testConstructorUsesExplicitOwnerAndHasNoDependencies() public {
        Board unconfigured = new Board(owner);
        assertEq(unconfigured.owner(), owner);
        assertEq(unconfigured.reporter(), address(0));
        Board.SnapshotInput memory input = _input(0, 0);
        vm.expectRevert(Board.NotConfigured.selector);
        unconfigured.beginEpoch(input);
        vm.expectRevert(Board.InvalidAddress.selector);
        new Board(address(0));
    }

    function testCountsRatingPortfolioAndPagination() public {
        uint64 id = _begin(2, 3);
        _append(id, _report(alice, 2, 10));
        _append(id, _report(bob, 1, 1));
        vm.prank(reporter);
        board.finalizeEpoch(id);
        (Board.Epoch memory epoch, bool stale, bool current) = board.summary();
        assertEq(epoch.snapshot.totalSeats, 8);
        assertEq(epoch.snapshot.activatedSeats, 3);
        assertEq(epoch.snapshot.walletCount, 2);
        assertEq(epoch.reporter, reporter);
        assertEq(epoch.seatNFT, nft);
        assertEq(epoch.methodologyHash, POLICY);
        assertFalse(stale);
        assertTrue(current);
        Board.Rating memory rating = board.walletRating(alice);
        assertTrue(rating.found);
        assertEq(rating.stats.rank, 1);
        assertEq(rating.stats.score, 6400); // 1000 + 1450 + 3000 + 750 + 200.
        assertEq(uint8(rating.tier), uint8(Board.Tier.Chad));
        assertEq(rating.stats.metrics.launches, 10);
        assertEq(rating.stats.metrics.totalClaimDelay / rating.stats.metrics.claimedClaims, 1 days);
        Board.TokenReport[] memory portfolio = board.walletTokens(id, alice);
        assertEq(portfolio[0].rewardHeld, 100e6);
        assertEq(portfolio[0].bought, 50e6);
        assertEq(portfolio[0].rewardSold, 0);
        Board.Leader[] memory page = board.leaderboard(id, 1, 100);
        assertEq(page.length, 1);
        assertEq(page[0].wallet, bob);
        assertEq(page[0].rank, 2);
        assertEq(board.leaderboard(id, type(uint32).max, 1).length, 0);
        Board.Rating memory absent = board.walletRating(stranger);
        assertFalse(absent.found);
        assertEq(absent.stats.rank, 0);
        assertEq(board.walletTokens(id, stranger).length, 0);
    }

    function testIncompleteEpochNeverChangesPublicRanking() public {
        uint64 first = _publishOne();
        vm.roll(vm.getBlockNumber() + 100);
        vm.warp(vm.getBlockTimestamp() + 1 hours);
        uint64 second = _begin(2, 3);
        _append(second, _report(bob, 1, 30));
        assertEq(board.latestEpoch(), first);
        assertEq(board.walletRating(alice).stats.rank, 1);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.walletAt(second, bob);
        vm.prank(reporter);
        vm.expectRevert(Board.IncompleteSnapshot.selector);
        board.finalizeEpoch(second);
        _append(second, _report(alice, 2, 10));
        vm.prank(reporter);
        board.finalizeEpoch(second);
        assertEq(board.walletRating(alice).stats.rank, 2);
        assertEq(board.walletAt(first, alice).stats.rank, 1);
    }

    function testSeatTransferRemovesOldWalletFromLatestButPreservesHistory() public {
        uint64 first = _publishOne();
        vm.roll(vm.getBlockNumber() + 100);
        vm.warp(vm.getBlockTimestamp() + 1 hours);
        uint64 second = _begin(1, 2);
        _append(second, _report(bob, 2, 0));
        vm.prank(reporter);
        board.finalizeEpoch(second);
        assertFalse(board.walletRating(alice).found);
        assertTrue(board.walletRating(bob).found);
        assertTrue(board.walletAt(first, alice).found);
    }

    function testEmptyCensusCanBePublished() public {
        uint64 id = _begin(0, 0);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        assertEq(board.leaderboard(id, 0, 100).length, 0);
        assertFalse(board.walletRating(alice).found);
    }

    function testScoreMaximumAndTierBoundaries() public view {
        Board.WalletReport memory r = _report(alice, 1, type(uint32).max);
        r.metrics.totalClaimDelay = 0;
        r.metrics.maxClaimDelay = 0;
        r.metrics.interactions = 100;
        r.metrics.distinctApps = 100;
        r.tokens[0].bought = type(uint128).max;
        (uint16 score, uint16 retention, uint16 support) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 10_000);
        assertEq(retention, 10_000);
        assertEq(support, 10_000);
        assertEq(uint8(board.tierFor(2499)), 0);
        assertEq(uint8(board.tierFor(2500)), 1);
        assertEq(uint8(board.tierFor(5000)), 2);
        assertEq(uint8(board.tierFor(7500)), 3);
    }

    function testUnclaimedAndSlowClaimsEarnNoSpeedPoints() public view {
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.metrics = Board.WalletMetrics(1, 0, 5, 0, 0, 0, 0, 0);
        r.tokens[0] = Board.TokenReport(0, 0, 0, 0, 0, 0, 0, 0);
        (uint16 score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 0);
        r = _report(alice, 1, 0);
        r.metrics.totalClaimDelay = 31 days;
        r.metrics.maxClaimDelay = 31 days;
        (score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 3950);
        r.metrics.totalClaimDelay = 0;
        r.metrics.maxClaimDelay = 0;
        r.metrics.eligibleClaims = 2;
        (score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 4700); // Half of eligible allocations claimed: 750 speed points.
    }

    function testRewardSaleAndOrdinaryTransferAreSeparate() public {
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.tokens[0] = Board.TokenReport(100, 50, 70, 20, 10, 70, 20, 1000);
        // A gift of 990 tokens does not restore the attributed rewards already disposed of.
        (uint16 score, uint16 retention,) = board.previewScore(r.metrics, r.tokens);
        assertEq(retention, 1000);
        assertEq(score, 1950);
        uint64 id = _begin(1, 1);
        _append(id, r);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        Board.TokenReport memory p = board.walletTokens(id, alice)[0];
        assertEq(p.rewardHeld + p.rewardSold + p.rewardOtherOut, p.claimed);
        assertEq(p.rewardSold, 70);
        assertEq(p.rewardOtherOut, 20);
    }

    function testHeterogeneousTokenDecimalsUseRatiosNotRawSums() public {
        address second = address(0x3000);
        vm.etch(second, hex"00");
        Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](2);
        policies[0] = Board.TokenPolicy(token, 100e6);
        policies[1] = Board.TokenPolicy(second, 100e18);
        vm.prank(owner);
        board.setTokenPolicies(policies);
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.tokens = new Board.TokenReport[](2);
        r.tokens[0] = Board.TokenReport(100e6, 100e6, 50e6, 0, 50e6, 50e6, 0, 150e6);
        r.tokens[1] = Board.TokenReport(100e18, 0, 0, 0, 100e18, 0, 0, 100e18);
        (uint16 score, uint16 retention, uint16 support) = board.previewScore(r.metrics, r.tokens);
        assertEq(retention, 7500);
        assertEq(support, 5000);
        assertEq(score, 4650);
    }

    function testOwnershipRequiresAcceptanceAndFactoryHasNoPrivilege() public {
        vm.prank(stranger);
        vm.expectRevert(Board.Unauthorized.selector);
        board.setReporter(stranger);
        vm.prank(owner);
        vm.expectRevert(Board.InvalidAddress.selector);
        board.transferOwnership(address(0));
        vm.prank(owner);
        board.transferOwnership(alice);
        assertEq(board.owner(), owner);
        vm.prank(bob);
        vm.expectRevert(Board.Unauthorized.selector);
        board.acceptOwnership();
        vm.prank(alice);
        board.acceptOwnership();
        assertEq(board.owner(), alice);
        assertEq(board.pendingOwner(), address(0));
        vm.prank(owner);
        vm.expectRevert(Board.Unauthorized.selector);
        board.setReporter(stranger);
    }

    function testAllWritePathsRejectUnauthorizedCallers() public {
        Board.TokenPolicy[] memory policies = _policies();
        Board.SnapshotInput memory input = _input(1, 1);
        vm.startPrank(stranger);
        vm.expectRevert(Board.Unauthorized.selector);
        board.setSources(nft, POLICY);
        vm.expectRevert(Board.Unauthorized.selector);
        board.setTokenPolicies(policies);
        vm.expectRevert(Board.Unauthorized.selector);
        board.setMaxAge(1 days);
        vm.expectRevert(Board.Unauthorized.selector);
        board.transferOwnership(stranger);
        vm.expectRevert(Board.Unauthorized.selector);
        board.beginEpoch(input);
        vm.stopPrank();
        uint64 id = _begin(1, 1);
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 1, 1);
        vm.startPrank(stranger);
        vm.expectRevert(Board.Unauthorized.selector);
        board.appendWallets(id, reports);
        vm.expectRevert(Board.Unauthorized.selector);
        board.finalizeEpoch(id);
        vm.expectRevert(Board.Unauthorized.selector);
        board.abortEpoch(id);
        vm.stopPrank();
    }

    function testConfigurationCannotChangeMidEpochAndOwnerCanRecover() public {
        uint64 id = _begin(1, 1);
        Board.TokenPolicy[] memory policies = _policies();
        Board.SnapshotInput memory input = _input(1, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.PendingEpoch.selector);
        board.beginEpoch(input);
        vm.startPrank(owner);
        vm.expectRevert(Board.PendingEpoch.selector);
        board.setReporter(stranger);
        vm.expectRevert(Board.PendingEpoch.selector);
        board.setSources(nft, POLICY);
        vm.expectRevert(Board.PendingEpoch.selector);
        board.setTokenPolicies(policies);
        vm.expectRevert(Board.PendingEpoch.selector);
        board.setMaxAge(1 days);
        board.abortEpoch(id);
        board.setReporter(stranger);
        vm.stopPrank();
        input.configuration = board.configuration();
        assertEq(uint8(board.getEpoch(id).status), uint8(Board.Status.Aborted));
        assertEq(board.pendingEpoch(), 0);
        vm.prank(reporter);
        vm.expectRevert(Board.Unauthorized.selector);
        board.beginEpoch(input);
        vm.prank(stranger);
        uint64 next = board.beginEpoch(input);
        assertGt(next, id);
    }

    function testReporterCanBeRevokedAndUnconfiguredDependenciesFailClearly() public {
        vm.prank(owner);
        board.setReporter(address(0));
        Board.SnapshotInput memory input = _input(0, 0);
        vm.prank(reporter);
        vm.expectRevert(Board.NotConfigured.selector);
        board.beginEpoch(input);
        vm.prank(owner);
        board.setReporter(reporter);
        vm.etch(nft, hex"");
        vm.prank(reporter);
        vm.expectRevert(Board.NotConfigured.selector);
        board.beginEpoch(input);
        vm.etch(nft, hex"00");
        vm.etch(token, hex"");
        vm.prank(reporter);
        vm.expectRevert(Board.NotConfigured.selector);
        board.beginEpoch(input);
        Board fresh = new Board(owner);
        vm.prank(owner);
        fresh.setReporter(reporter);
        vm.prank(reporter);
        vm.expectRevert(Board.NotConfigured.selector);
        fresh.beginEpoch(input);
    }

    function testInvalidConfigurationRevertsAtomically() public {
        vm.startPrank(owner);
        vm.expectRevert(Board.InvalidAddress.selector);
        board.setSources(address(0), POLICY);
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setSources(nft, bytes32(0));
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setMaxAge(3599);
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setMaxAge(30 days + 1);
        Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](0);
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setTokenPolicies(policies);
        policies = new Board.TokenPolicy[](17);
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setTokenPolicies(policies);
        policies = new Board.TokenPolicy[](2);
        policies[0] = Board.TokenPolicy(token, 1);
        policies[1] = Board.TokenPolicy(token, 1);
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setTokenPolicies(policies);
        policies = _policies();
        policies[0].supportTarget = 0;
        vm.expectRevert(Board.InvalidConfiguration.selector);
        board.setTokenPolicies(policies);
        vm.stopPrank();
        assertEq(board.tokenPolicies()[0].supportTarget, 100e6);
    }

    function testBadCountsTimesAndHashesRejected() public {
        Board.SnapshotInput memory input = _input(2, 1);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input = _input(0, 1);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input = _input(1, 1);
        input.totalSeats = 0;
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input = _input(1, 1);
        input.timestamp = uint64(vm.getBlockTimestamp() + 1);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input.timestamp = uint64(vm.getBlockTimestamp() - 2 days - 1);
        _expectBadInput(input, Board.SnapshotTooOld.selector);
        input = _input(1, 1);
        input.blockNumber = uint64(vm.getBlockNumber());
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input = _input(1, 1);
        input.evidenceHash = bytes32(0);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        input = _input(1, 1);
        input.blockHash = keccak256("incorrect hash");
        _expectBadInput(input, Board.BlockHashMismatch.selector);
    }

    function _expectBadInput(Board.SnapshotInput memory input, bytes4 error_) private {
        vm.prank(reporter);
        vm.expectRevert(error_);
        board.beginEpoch(input);
    }

    function testOldHashesRemainExplicitlyReporterAttested() public {
        Board.SnapshotInput memory input = _input(0, 0);
        input.blockNumber = 1;
        input.blockHash = keccak256("archive block hash beyond blockhash window");
        vm.prank(reporter);
        uint64 id = board.beginEpoch(input);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        assertEq(board.getEpoch(id).snapshot.blockHash, input.blockHash);
    }

    function testSnapshotHeightAndTimeMustBothAdvance() public {
        _publishOne();
        Board.SnapshotInput memory input = _input(0, 0);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        vm.roll(vm.getBlockNumber() + 1);
        input = _input(0, 0);
        _expectBadInput(input, Board.InvalidSnapshot.selector);
        vm.warp(vm.getBlockTimestamp() + 1);
        input = _input(0, 0);
        vm.prank(reporter);
        board.beginEpoch(input);
    }

    function testPreparedReportCannotBeRelabeledAfterConfigurationChanges() public {
        Board.SnapshotInput memory input = _input(0, 0);
        vm.prank(owner);
        board.setSources(nft, keccak256("changed methodology"));
        _expectBadInput(input, Board.InvalidConfiguration.selector);
        input.configuration = board.configuration();
        vm.prank(reporter);
        board.beginEpoch(input);
    }

    function testPublishedTokenPolicyAndAttributionRemainImmutable() public {
        uint64 id = _publishOne();
        Board.TokenPolicy[] memory policies = _policies();
        policies[0].supportTarget = 500e6;
        vm.prank(owner);
        board.setTokenPolicies(policies);
        assertEq(board.epochTokenPolicies(id)[0].supportTarget, 100e6);
        assertEq(board.walletAt(id, alice).stats.score, 6400);
        assertFalse(board.walletAt(id, alice).currentConfiguration);
    }

    function testFreshnessAtBoundaryAndAfterConfigurationChange() public {
        uint64 id = _publishOne();
        uint64 observed = board.getEpoch(id).snapshot.timestamp;
        vm.warp(observed + 2 days);
        assertFalse(board.walletRating(alice).stale);
        vm.warp(observed + 2 days + 1);
        assertTrue(board.walletRating(alice).stale);
        assertTrue(board.walletRating(alice).currentConfiguration);
        vm.prank(owner);
        board.setMaxAge(3 days);
        Board.Rating memory r = board.walletRating(alice);
        assertTrue(r.stale);
        assertFalse(r.currentConfiguration);
        assertEq(board.getEpoch(id).maxAge, 2 days); // Old expiry cannot be silently extended.
    }

    function testCannotFinalizeExpiredDraft() public {
        uint64 id = _begin(1, 1);
        _append(id, _report(alice, 1, 1));
        vm.warp(vm.getBlockTimestamp() + 2 days);
        vm.prank(reporter);
        vm.expectRevert(Board.SnapshotTooOld.selector);
        board.finalizeEpoch(id);
        assertEq(board.latestEpoch(), 0);
        vm.prank(owner);
        board.abortEpoch(id);
    }

    function testDuplicateWalletRejectedAcrossBatches() public {
        uint64 id = _begin(2, 2);
        _append(id, _report(alice, 1, 1));
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 1, 0);
        vm.prank(reporter);
        vm.expectRevert(Board.DuplicateWallet.selector);
        board.appendWallets(id, reports);
        assertEq(board.getEpoch(id).walletsWritten, 1);
    }

    function testTieBreakerAndIncreasingScoreRejectedAcrossBatches() public {
        uint64 id = _begin(2, 2);
        _append(id, _report(alice, 1, 1));
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(bob, 1, 1); // bob < alice, so must come first when tied.
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidOrder.selector);
        board.appendWallets(id, reports);
        reports[0].metrics.launches = 2;
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidOrder.selector);
        board.appendWallets(id, reports);
        vm.prank(reporter);
        board.abortEpoch(id);
        id = _begin(2, 2);
        _append(id, _report(bob, 1, 1));
        _append(id, _report(alice, 1, 1));
        vm.prank(reporter);
        board.finalizeEpoch(id);
        assertEq(board.walletRating(bob).stats.rank, 1);
    }

    function testInvalidBatchIsFullyRolledBack() public {
        uint64 id = _begin(2, 2);
        Board.WalletReport[] memory reports = new Board.WalletReport[](2);
        reports[0] = _report(bob, 1, 1);
        reports[1] = _report(alice, 1, 2);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidOrder.selector);
        board.appendWallets(id, reports);
        assertEq(board.getEpoch(id).walletsWritten, 0);
        assertEq(board.getEpoch(id).seatsWritten, 0);
        reports[1].metrics.launches = 1;
        vm.prank(reporter);
        board.appendWallets(id, reports);
        assertEq(board.getEpoch(id).walletsWritten, 2);
    }

    function testIncompleteSeatCensusAndOversizedSeatClaimsFail() public {
        uint64 id = _begin(1, 2);
        _append(id, _report(alice, 1, 1));
        vm.prank(reporter);
        vm.expectRevert(Board.IncompleteSnapshot.selector);
        board.finalizeEpoch(id);
        vm.prank(owner);
        board.abortEpoch(id);
        id = _begin(1, 1);
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 2, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidSnapshot.selector);
        board.appendWallets(id, reports);
        reports[0].metrics.activeSeats = 0;
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidWallet.selector);
        board.appendWallets(id, reports);
        reports[0] = _report(address(0), 1, 0);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidWallet.selector);
        board.appendWallets(id, reports);
    }

    function testInvalidMetricsAndInventedHoldingsRejected() public {
        Board.WalletReport memory r = _report(alice, 1, 1);
        r.metrics.claimedClaims = 2;
        _expectBadReport(r, Board.InvalidMetrics.selector);
        r = _report(alice, 1, 1);
        r.metrics.distinctApps = 3;
        _expectBadReport(r, Board.InvalidMetrics.selector);
        r = _report(alice, 1, 1);
        r.metrics.maxClaimDelay += 1;
        _expectBadReport(r, Board.InvalidMetrics.selector);
        r = _report(alice, 1, 1);
        r.metrics.totalClaimDelay += 1;
        _expectBadReport(r, Board.InvalidMetrics.selector);
        r = _report(alice, 1, 1);
        r.tokens[0].rewardHeld += 1;
        _expectBadReport(r, Board.InvalidTokenReport.selector);
        r = _report(alice, 1, 1);
        r.tokens[0].balance = 1;
        _expectBadReport(r, Board.InvalidTokenReport.selector);
        r = _report(alice, 1, 1);
        r.tokens[0].rewardHeld = 90e6;
        r.tokens[0].rewardSold = 10e6;
        _expectBadReport(r, Board.InvalidTokenReport.selector);
        r.tokens[0].rewardSold = 0;
        r.tokens[0].rewardOtherOut = 10e6;
        _expectBadReport(r, Board.InvalidTokenReport.selector);
        r = _report(alice, 1, 1);
        r.tokens = new Board.TokenReport[](0);
        _expectBadReport(r, Board.InvalidTokenReport.selector);
        r = _report(alice, 1, 1);
        r.tokens[0] = Board.TokenReport(0, 0, 0, 0, 0, 0, 0, 0);
        _expectBadReport(r, Board.InvalidMetrics.selector);
        r = _report(alice, 1, 1);
        r.metrics.claimedClaims = 0;
        r.metrics.totalClaimDelay = 0;
        r.metrics.maxClaimDelay = 0;
        _expectBadReport(r, Board.InvalidMetrics.selector);
    }

    function _expectBadReport(Board.WalletReport memory r, bytes4 error_) private {
        vm.expectRevert(error_);
        board.previewScore(r.metrics, r.tokens);
    }

    function testInvalidPagesBatchesAndEpochsFail() public {
        vm.expectRevert(Board.NoPublishedEpoch.selector);
        board.summary();
        vm.expectRevert(Board.NoPublishedEpoch.selector);
        board.walletRating(alice);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.getEpoch(0);
        uint64 id = _begin(30, 30);
        Board.WalletReport[] memory reports = new Board.WalletReport[](0);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidBatch.selector);
        board.appendWallets(id, reports);
        reports = new Board.WalletReport[](21);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidBatch.selector);
        board.appendWallets(id, reports);
        vm.prank(owner);
        board.abortEpoch(id);
        id = _publishOne();
        vm.expectRevert(Board.InvalidPage.selector);
        board.leaderboard(id, 0, 0);
        vm.expectRevert(Board.InvalidPage.selector);
        board.leaderboard(id, 0, 101);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.finalizeEpoch(id);
        vm.prank(owner);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.abortEpoch(id);
    }

    function testMaximumBatchAndTokenCounts() public {
        Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](16);
        for (uint256 i; i < policies.length; ++i) {
            address asset = address(uint160(0x2000 + i));
            vm.etch(asset, hex"00");
            policies[i] = Board.TokenPolicy(asset, 100);
        }
        vm.prank(owner);
        board.setTokenPolicies(policies);
        uint64 id = _begin(20, 20);
        Board.WalletReport[] memory reports = new Board.WalletReport[](20);
        for (uint256 i; i < reports.length; ++i) {
            reports[i] = _report(address(uint160(0x4000 + i)), 1, 10);
            reports[i].tokens = new Board.TokenReport[](16);
            for (uint256 j; j < 16; ++j) {
                reports[i].tokens[j] = Board.TokenReport(300, 100, 100, 100, 100, 100, 100, 100);
            }
        }
        vm.prank(reporter);
        board.appendWallets(id, reports);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        assertEq(board.leaderboard(id, 0, 100).length, 20);
        assertEq(board.walletRating(address(0x4013)).stats.rank, 20);
        assertEq(board.walletTokens(id, address(0x4000)).length, 16);
    }

    function testNoNativeValueCustodyOrFallback() public {
        vm.deal(stranger, 1 ether);
        vm.prank(stranger);
        (bool ok,) = address(board).call{value: 1}("");
        assertFalse(ok);
        (ok,) = address(board).call(hex"ffffffff");
        assertFalse(ok);
    }

    function testRuntimeContainsNoForbiddenOpcodesAndFitsDeploymentLimits() public view {
        bytes memory code = address(board).code;
        assertLe(code.length, 24_576);
        assertLe(type(Board).creationCode.length + 32, 49_152);
        for (uint256 i; i < code.length; ++i) {
            uint8 op = uint8(code[i]);
            if (op >= 0x60 && op <= 0x7f) {
                i += op - 0x5f;
                continue;
            }
            assertTrue(op != 0xf4 && op != 0xf2 && op != 0xff);
        }
    }

    function testFuzzScoreBoundsAndRewardAccounting(
        uint128 claimed,
        uint128 bought,
        uint128 soldSeed,
        uint128 otherSeed,
        uint32 launches,
        uint32 delay
    ) public view {
        claimed = uint128(bound(claimed, 1, type(uint128).max));
        uint128 sold = uint128(bound(soldSeed, 0, claimed));
        uint128 other = uint128(bound(otherSeed, 0, claimed - sold));
        uint128 held = claimed - sold - other;
        Board.WalletReport memory r = _report(alice, 1, launches);
        r.metrics.totalClaimDelay = delay;
        r.metrics.maxClaimDelay = delay;
        r.tokens[0] = Board.TokenReport(claimed, bought, sold, other, held, sold, other, held);
        (uint16 score, uint16 retention, uint16 support) = board.previewScore(r.metrics, r.tokens);
        assertLe(score, 10_000);
        assertLe(retention, 10_000);
        assertLe(support, 10_000);
        assertEq(retention, uint256(held) * 10_000 / claimed);
        assertEq(uint256(held) + sold + other, claimed);
    }

    function testFuzzScoreNeverIncreasesWhenMoreRewardsAreDisposed(uint128 heldSeed, uint128 lossSeed) public view {
        uint128 held = uint128(bound(heldSeed, 0, 100e6));
        uint128 loss = uint128(bound(lossSeed, 0, held));
        Board.WalletReport memory r = _report(alice, 1, 1);
        r.tokens[0] = Board.TokenReport(100e6, 0, 100e6 - held, 0, held, 100e6 - held, 0, held);
        (uint16 beforeScore,,) = board.previewScore(r.metrics, r.tokens);
        r.tokens[0].rewardHeld -= loss;
        r.tokens[0].rewardSold += loss;
        r.tokens[0].sold += loss;
        r.tokens[0].balance -= loss;
        (uint16 afterScore,,) = board.previewScore(r.metrics, r.tokens);
        assertLe(afterScore, beforeScore);
    }
}
