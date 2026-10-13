// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IMDChadBoard as Board} from "../src/IMDChadBoard.sol";
import {BoardFixture} from "./IMDChadBoard.t.sol";

/// @notice Edge and failure paths not covered by the base suite, plus scoring properties.
contract IMDChadBoardAdversarialTest is BoardFixture {
    event WalletAppended(uint64 indexed epoch, address indexed wallet, uint32 rank, uint16 score);
    event EpochPublished(uint64 indexed epoch, uint32 wallets, uint64 activatedSeats);

    // ---------------------------------------------------------------- lifecycle

    function testAppendAndFinalizeRejectedOncePublished() public {
        uint64 id = _publishOne();
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(bob, 1, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.appendWallets(id, reports);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.finalizeEpoch(id);
        assertEq(board.walletRating(alice).stats.rank, 1);
        assertFalse(board.walletRating(bob).found);
    }

    function testAbortedEpochIsDeadAndInvisible() public {
        uint64 id = _begin(2, 2);
        _append(id, _report(alice, 1, 5));
        vm.prank(reporter);
        board.abortEpoch(id);
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(bob, 1, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.appendWallets(id, reports);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.finalizeEpoch(id);
        vm.prank(owner);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.abortEpoch(id);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.walletAt(id, alice);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.walletTokens(id, alice);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.leaderboard(id, 0, 1);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.epochTokenPolicies(id);
        vm.expectRevert(Board.NoPublishedEpoch.selector);
        board.walletRating(alice);
        assertEq(board.latestEpoch(), 0);
        // The same wallet can be reported afresh in the next census.
        uint64 next = _begin(1, 1);
        _append(next, _report(alice, 1, 5));
        vm.prank(reporter);
        board.finalizeEpoch(next);
        assertEq(board.walletRating(alice).epoch, next);
    }

    function testDraftEpochQueriesRevert() public {
        uint64 id = _begin(1, 1);
        _append(id, _report(alice, 1, 1));
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.walletTokens(id, alice);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.leaderboard(id, 0, 1);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.epochTokenPolicies(id);
        assertEq(uint8(board.getEpoch(id).status), uint8(Board.Status.Building));
    }

    function testWrongEpochIdsRejected() public {
        uint64 id = _begin(1, 1);
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 1, 1);
        vm.startPrank(reporter);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.appendWallets(0, reports);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.appendWallets(id + 1, reports);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.finalizeEpoch(0);
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.abortEpoch(id + 1);
        vm.stopPrank();
        vm.expectRevert(Board.InvalidEpoch.selector);
        board.getEpoch(id + 1);
    }

    function testBatchCannotExceedDeclaredWalletCount() public {
        uint64 id = _begin(1, 3);
        Board.WalletReport[] memory reports = new Board.WalletReport[](2);
        reports[0] = _report(bob, 1, 2);
        reports[1] = _report(alice, 1, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidBatch.selector);
        board.appendWallets(id, reports);
        _append(id, _report(alice, 1, 1));
        Board.WalletReport[] memory one = new Board.WalletReport[](1);
        one[0] = _report(bob, 1, 0);
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidBatch.selector);
        board.appendWallets(id, one);
    }

    function testDuplicateWithinOneBatchRejected() public {
        uint64 id = _begin(2, 2);
        Board.WalletReport[] memory reports = new Board.WalletReport[](2);
        reports[0] = _report(alice, 1, 2);
        reports[1] = _report(alice, 1, 1);
        vm.prank(reporter);
        vm.expectRevert(Board.DuplicateWallet.selector);
        board.appendWallets(id, reports);
        assertEq(board.getEpoch(id).walletsWritten, 0);
    }

    function testAppendRejectsClaimDelayLongerThanSnapshotHistory() public {
        uint64 id = _begin(1, 1);
        Board.WalletReport memory r = _report(alice, 1, 1);
        uint64 snapshotTime = board.getEpoch(id).snapshot.timestamp;
        r.metrics.maxClaimDelay = snapshotTime + 1;
        r.metrics.totalClaimDelay = snapshotTime + 1;
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = r;
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.appendWallets(id, reports);
        r.metrics.maxClaimDelay = snapshotTime;
        r.metrics.totalClaimDelay = snapshotTime;
        _append(id, r);
    }

    function testAppendRejectsTokenReportForDifferentPolicyCount() public {
        uint64 id = _begin(1, 1);
        Board.WalletReport memory r = _report(alice, 1, 1);
        Board.TokenReport[] memory tokens = new Board.TokenReport[](2);
        tokens[0] = r.tokens[0];
        r.tokens = tokens;
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = r;
        vm.prank(reporter);
        vm.expectRevert(Board.InvalidTokenReport.selector);
        board.appendWallets(id, reports);
    }

    function testRevokedReporterCannotWriteAndOldReporterLosesAccess() public {
        vm.prank(owner);
        board.setReporter(address(0));
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 1, 1);
        vm.startPrank(reporter);
        vm.expectRevert(Board.NotConfigured.selector);
        board.appendWallets(1, reports);
        vm.expectRevert(Board.NotConfigured.selector);
        board.finalizeEpoch(1);
        vm.expectRevert(Board.Unauthorized.selector);
        board.abortEpoch(1);
        vm.stopPrank();
    }

    function testOwnerIsNotReporterUnlessAppointed() public {
        Board.SnapshotInput memory input = _input(0, 0);
        vm.prank(owner);
        vm.expectRevert(Board.Unauthorized.selector);
        board.beginEpoch(input);
        uint64 id = _begin(1, 1);
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _report(alice, 1, 1);
        vm.startPrank(owner);
        vm.expectRevert(Board.Unauthorized.selector);
        board.appendWallets(id, reports);
        vm.expectRevert(Board.Unauthorized.selector);
        board.finalizeEpoch(id);
        vm.stopPrank();
    }

    function testPendingOwnerCanBeReplacedAndStalePendingCannotAccept() public {
        vm.startPrank(owner);
        board.transferOwnership(alice);
        board.transferOwnership(bob);
        vm.stopPrank();
        vm.prank(alice);
        vm.expectRevert(Board.Unauthorized.selector);
        board.acceptOwnership();
        vm.prank(bob);
        board.acceptOwnership();
        assertEq(board.owner(), bob);
        vm.prank(bob);
        vm.expectRevert(Board.Unauthorized.selector);
        board.acceptOwnership(); // Cannot accept twice.
    }

    function testEventsCarryRankAndScore() public {
        uint64 id = _begin(1, 2);
        vm.expectEmit(true, true, false, true, address(board));
        emit WalletAppended(id, alice, 1, 6400);
        _append(id, _report(alice, 2, 10));
        vm.expectEmit(true, false, false, true, address(board));
        emit EpochPublished(id, 1, 2);
        vm.prank(reporter);
        board.finalizeEpoch(id);
    }

    // ---------------------------------------------------------------- time & hash boundaries

    function testBlockHashCheckedExactlyWithin256Blocks() public {
        uint64 height = uint64(vm.getBlockNumber() - 256);
        vm.setBlockhash(height, keccak256("real"));
        Board.SnapshotInput memory input = _input(0, 0);
        input.blockNumber = height;
        input.blockHash = keccak256("forged");
        vm.prank(reporter);
        vm.expectRevert(Board.BlockHashMismatch.selector);
        board.beginEpoch(input);
        input.blockHash = keccak256("real");
        vm.prank(reporter);
        board.beginEpoch(input);
    }

    function testFinalizeAtExactMaxAgeBoundary() public {
        uint64 id = _begin(1, 1);
        _append(id, _report(alice, 1, 1));
        uint64 observed = board.getEpoch(id).snapshot.timestamp;
        vm.warp(observed + 2 days);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        assertEq(board.getEpoch(id).publishedAt, observed + 2 days);
    }

    function testSnapshotAtExactMaxAgeAccepted() public {
        Board.SnapshotInput memory input = _input(0, 0);
        input.timestamp = uint64(vm.getBlockTimestamp() - 2 days);
        vm.prank(reporter);
        board.beginEpoch(input);
    }

    function testSnapshotFieldEdgesRejected() public {
        Board.SnapshotInput memory input = _input(0, 0);
        input.blockNumber = 0;
        _expectBadSnapshot(input, Board.InvalidSnapshot.selector);
        input = _input(0, 0);
        input.timestamp = 0;
        _expectBadSnapshot(input, Board.InvalidSnapshot.selector);
        input = _input(0, 0);
        input.blockHash = bytes32(0);
        _expectBadSnapshot(input, Board.InvalidSnapshot.selector);
        input = _input(0, 0);
        input.blockNumber = uint64(vm.getBlockNumber() + 1);
        _expectBadSnapshot(input, Board.InvalidSnapshot.selector);
        input = _input(0, 0);
        input.configuration = board.configuration() + 1;
        _expectBadSnapshot(input, Board.InvalidConfiguration.selector);
        // Fully empty seat collection is a valid census.
        input = _input(0, 0);
        input.totalSeats = 0;
        vm.prank(reporter);
        board.beginEpoch(input);
    }

    function _expectBadSnapshot(Board.SnapshotInput memory input, bytes4 error_) private {
        vm.prank(reporter);
        vm.expectRevert(error_);
        board.beginEpoch(input);
    }

    function testNewMaxAgeAppliesOnlyToLaterEpochs() public {
        vm.prank(owner);
        board.setMaxAge(1 hours);
        Board.SnapshotInput memory input = _input(1, 1);
        uint64 id;
        vm.prank(reporter);
        id = board.beginEpoch(input); // Exactly 1 hour old.
        _append(id, _report(alice, 1, 1));
        vm.warp(vm.getBlockTimestamp() + 1);
        vm.prank(reporter);
        vm.expectRevert(Board.SnapshotTooOld.selector);
        board.finalizeEpoch(id);
    }

    // ---------------------------------------------------------------- queries

    function testLeaderboardOffsetAtAndBeyondEnd() public {
        uint64 id = _publishOne();
        assertEq(board.leaderboard(id, 1, 1).length, 0);
        Board.Leader[] memory page = board.leaderboard(id, 0, 1);
        assertEq(page.length, 1);
        assertEq(page[0].wallet, alice);
        assertEq(page[0].activeSeats, 2);
        assertEq(uint8(page[0].tier), uint8(Board.Tier.Chad));
        assertEq(board.leaderboard(id, 0, 100).length, 1);
    }

    function testPreviewRequiresPolicies() public {
        Board fresh = new Board(owner);
        Board.WalletReport memory r = _report(alice, 1, 1);
        vm.expectRevert(Board.NotConfigured.selector);
        fresh.previewScore(r.metrics, r.tokens);
    }

    function testPreviewRejectsZeroSeats() public {
        Board.WalletReport memory r = _report(alice, 0, 1);
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
    }

    function testExtremeTokenValuesDoNotOverflow() public view {
        Board.WalletReport memory r = _report(alice, type(uint32).max, type(uint32).max);
        uint128 max = type(uint128).max;
        r.tokens[0] = Board.TokenReport(max, max, max, max, max / 3, max / 3, max - 2 * (max / 3), max);
        (uint16 score, uint16 retention, uint16 support) = board.previewScore(r.metrics, r.tokens);
        assertEq(support, 10_000);
        assertEq(retention, 3333);
        assertLe(score, 10_000);
    }

    function testMaximumClaimDelayValues() public view {
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.metrics.eligibleClaims = type(uint32).max;
        r.metrics.claimedClaims = type(uint32).max;
        r.metrics.maxClaimDelay = type(uint64).max;
        r.metrics.totalClaimDelay = type(uint64).max;
        (uint16 score,,) = board.previewScore(r.metrics, r.tokens);
        // Average delay (max / max claims, ~136 years) is beyond the window: no speed points, no overflow.
        assertEq(score, 3950);
    }

    // ---------------------------------------------------------------- properties

    /// forge-config: default.fuzz.runs = 1000
    function testFuzzStoredScoreMatchesPreviewAndBounds(uint256 seed) public {
        Board.WalletReport memory r = _randomReport(alice, seed);
        (uint16 score, uint16 retention, uint16 support) = board.previewScore(r.metrics, r.tokens);
        uint64 id = _begin(1, r.metrics.activeSeats);
        _append(id, r);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        Board.Rating memory rating = board.walletRating(alice);
        assertEq(rating.stats.score, score);
        assertEq(rating.stats.retentionBps, retention);
        assertEq(rating.stats.supportBps, support);
        assertEq(uint8(rating.tier), uint8(board.tierFor(score)));
        assertLe(score, 10_000);
        Board.TokenReport memory t = board.walletTokens(id, alice)[0];
        assertEq(uint256(t.rewardHeld) + t.rewardSold + t.rewardOtherOut, t.claimed);
        assertLe(t.rewardHeld, t.balance);
    }

    /// forge-config: default.fuzz.runs = 1000
    function testFuzzMoreActivityNeverLowersScore(uint256 seed, uint8 kind, uint64 amount) public view {
        Board.WalletReport memory r = _randomReport(alice, seed);
        (uint16 before,,) = board.previewScore(r.metrics, r.tokens);
        kind = uint8(bound(kind, 0, 3));
        if (kind == 0) {
            r.metrics.launches = uint32(_min(uint256(r.metrics.launches) + amount, type(uint32).max));
        } else if (kind == 1) {
            uint32 extra = uint32(bound(amount, 0, 1000));
            r.metrics.interactions += extra;
            r.metrics.distinctApps = uint16(_min(uint256(r.metrics.distinctApps) + extra, r.metrics.interactions));
        } else if (kind == 2) {
            r.tokens[0].bought += amount;
            r.tokens[0].balance += amount;
        } else {
            // Faster claims (every delay shortened) never score lower.
            r.metrics.totalClaimDelay = r.metrics.totalClaimDelay / 2;
            r.metrics.maxClaimDelay = r.metrics.maxClaimDelay / 2;
            if (r.metrics.totalClaimDelay < r.metrics.maxClaimDelay) {
                r.metrics.totalClaimDelay = r.metrics.maxClaimDelay;
            }
        }
        (uint16 afterScore,,) = board.previewScore(r.metrics, r.tokens);
        assertGe(afterScore, before);
    }

    /// forge-config: default.fuzz.runs = 500
    function testFuzzLeaderboardPagesReassembleRanking(uint8 countSeed, uint8 pageSeed, uint256 seed) public {
        uint256 count = bound(countSeed, 1, 20);
        uint32 pageSize = uint32(bound(pageSeed, 1, 7));
        Board.WalletReport[] memory reports = new Board.WalletReport[](count);
        uint16[] memory scores = new uint16[](count);
        uint64 seats;
        for (uint256 i; i < count; ++i) {
            reports[i] = _randomReport(address(uint160(0x9000 + i)), uint256(keccak256(abi.encode(seed, i))));
            (scores[i],,) = board.previewScore(reports[i].metrics, reports[i].tokens);
            seats += reports[i].metrics.activeSeats;
        }
        // Insertion sort: score descending, then address ascending.
        for (uint256 i = 1; i < count; ++i) {
            for (uint256 j = i; j > 0 && scores[j] > scores[j - 1]; --j) {
                (scores[j], scores[j - 1]) = (scores[j - 1], scores[j]);
                (reports[j], reports[j - 1]) = (reports[j - 1], reports[j]);
            }
        }
        uint64 id = _begin(uint32(count), seats);
        vm.prank(reporter);
        board.appendWallets(id, reports);
        vm.prank(reporter);
        board.finalizeEpoch(id);
        uint256 seen;
        uint256 seatSum;
        for (uint32 offset; offset < count; offset += pageSize) {
            Board.Leader[] memory page = board.leaderboard(id, offset, pageSize);
            for (uint256 k; k < page.length; ++k) {
                assertEq(page[k].wallet, reports[seen].wallet);
                assertEq(page[k].rank, seen + 1);
                assertEq(page[k].score, scores[seen]);
                assertEq(board.walletAt(id, page[k].wallet).stats.rank, seen + 1);
                seatSum += page[k].activeSeats;
                ++seen;
            }
        }
        assertEq(seen, count);
        assertEq(seatSum, seats);
    }

    /// @dev Builds a report that is valid by construction from a seed (single token policy, target 100e6).
    function _randomReport(address wallet, uint256 seed) internal pure returns (Board.WalletReport memory r) {
        r.wallet = wallet;
        uint256 s = seed;
        r.metrics.activeSeats = uint32(1 + s % 3);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.launches = uint32(s % 40);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.eligibleClaims = uint32(s % 5);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.claimedClaims = r.metrics.eligibleClaims == 0 ? 0 : uint32(s % (r.metrics.eligibleClaims + 1));
        s = uint256(keccak256(abi.encode(s)));
        r.tokens = new Board.TokenReport[](1);
        if (r.metrics.claimedClaims != 0) {
            uint64 maxDelay = uint64(s % 40 days);
            s = uint256(keccak256(abi.encode(s)));
            uint64 total = maxDelay + uint64(s % (uint256(maxDelay) * (r.metrics.claimedClaims - 1) + 1));
            r.metrics.maxClaimDelay = maxDelay;
            r.metrics.totalClaimDelay = total;
            s = uint256(keccak256(abi.encode(s)));
            uint128 claimed = uint128(1 + s % 1e9);
            s = uint256(keccak256(abi.encode(s)));
            uint128 sold = uint128(s % (claimed + 1));
            s = uint256(keccak256(abi.encode(s)));
            uint128 other = uint128(s % (claimed - sold + 1));
            uint128 held = claimed - sold - other;
            r.tokens[0] = Board.TokenReport(claimed, 0, sold, other, held, sold, other, held);
        }
        s = uint256(keccak256(abi.encode(s)));
        uint128 bought = uint128(s % 300e6);
        r.tokens[0].bought = bought;
        r.tokens[0].balance += bought;
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.interactions = uint32(s % 30);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.distinctApps = uint16(s % (uint256(r.metrics.interactions) + 1));
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
