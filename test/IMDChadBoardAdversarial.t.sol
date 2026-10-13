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

    /// @dev The history check only bites on a chain younger than CLAIM_WINDOW, since the window cap is tested
    ///      first; here the chain is 10 days old so a delay of the snapshot's full age is the exact limit.
    function testAppendRejectsClaimDelayLongerThanSnapshotHistory() public {
        vm.warp(10 days);
        uint64 id = _begin(1, 1);
        Board.WalletReport memory r = _report(alice, 1, 1);
        uint64 snapshotTime = board.getEpoch(id).snapshot.timestamp;
        assertLt(snapshotTime, board.CLAIM_WINDOW());
        r.metrics.maxClaimDelay = snapshotTime + 1;
        r.metrics.totalClaimDelay = snapshotTime + 1;
        // Preview has no snapshot context and accepts the metrics; the append is what knows the history.
        board.previewScore(r.metrics, r.tokens);
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

    /// @dev At distance 257 the EVM no longer serves the hash, so the check is skipped and any hash is stored
    ///      as reporter-attested; at 256 it is still enforced. Documented trust boundary, pinned here.
    function testBlockHashCheckSkippedExactlyBeyond256Blocks() public {
        assertEq(vm.getBlockNumber(), 1000);
        uint64 justInside = 744; // 1000 - 256
        uint64 justOutside = 743; // 1000 - 257
        vm.setBlockhash(justInside, keccak256("real inside"));
        vm.setBlockhash(justOutside, keccak256("real outside"));
        Board.SnapshotInput memory input = _input(0, 0);
        input.blockNumber = justInside;
        input.blockHash = keccak256("forged");
        vm.prank(reporter);
        vm.expectRevert(Board.BlockHashMismatch.selector);
        board.beginEpoch(input);
        input.blockNumber = justOutside;
        vm.prank(reporter);
        uint64 id = board.beginEpoch(input);
        assertEq(board.getEpoch(id).snapshot.blockNumber, justOutside);
        assertEq(board.getEpoch(id).snapshot.blockHash, keccak256("forged"));
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

    function testMaximumClaimDelayValues() public {
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.metrics.eligibleClaims = type(uint32).max;
        r.metrics.claimedClaims = type(uint32).max;
        // Uncapped delays are not valid observations: the indexer must cap each claim at the window.
        r.metrics.maxClaimDelay = type(uint64).max;
        r.metrics.totalClaimDelay = type(uint64).max;
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
        // The largest valid metrics: every one of 2**32-1 claims at exactly the window. No overflow, no points.
        r.metrics.maxClaimDelay = uint64(board.CLAIM_WINDOW());
        r.metrics.totalClaimDelay = uint64(board.CLAIM_WINDOW()) * uint64(type(uint32).max);
        (uint16 score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 3950);
        // One claim finished a window-length earlier moves the sum below claims * max and still earns nothing.
        r.metrics.totalClaimDelay -= 1;
        (score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 3950);
    }

    /// @dev Speed points are 1500 * (window * claims - total) / (window * eligible), floored: the first point
    ///      needs 1728 s of headroom under the window (1500 * 1728 == 30 days).
    function testClaimSpeedPointsAtTheWindowBoundary() public view {
        uint64 window = uint64(board.CLAIM_WINDOW());
        assertEq(window, 30 days);
        assertEq(_speedScore(window, window), 3000);
        assertEq(_speedScore(window - 1, window - 1), 3000);
        assertEq(_speedScore(window - 1727, window - 1727), 3000);
        assertEq(_speedScore(window - 1728, window - 1728), 3001);
        assertEq(_speedScore(window - 1729, window - 1729), 3001);
        assertEq(_speedScore(window - 2 * 1728, window - 2 * 1728), 3002);
        // The floor also works against the fast claimer: the full 1500 needs a zero delay.
        assertEq(_speedScore(1729, 1729), 4498);
        assertEq(_speedScore(1728, 1728), 4499);
        assertEq(_speedScore(1, 1), 4499);
        assertEq(_speedScore(0, 0), 4500);
    }

    /// @dev One claim, fully held, no launches, no apps, nothing bought: score is 3000 retention + speed points.
    function _speedScore(uint64 total, uint64 max) private view returns (uint16 score) {
        Board.WalletMetrics memory m = Board.WalletMetrics(1, 0, 1, 1, total, max, 0, 0);
        Board.TokenReport[] memory tokens = new Board.TokenReport[](1);
        tokens[0] = Board.TokenReport(1, 0, 0, 0, 1, 0, 0, 1);
        (score,,) = board.previewScore(m, tokens);
    }

    function testTotalDelayBoundedByClaimsTimesMaxDelay() public {
        uint64 window = uint64(board.CLAIM_WINDOW());
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.metrics.eligibleClaims = 2;
        r.metrics.claimedClaims = 2;
        r.metrics.maxClaimDelay = window;
        r.metrics.totalClaimDelay = 2 * window; // Exactly claims * max is the largest consistent sum.
        (uint16 score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 3950);
        r.metrics.totalClaimDelay = 2 * window + 1;
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
        // The same bound with a sub-window maximum: one second over is rejected.
        r.metrics.maxClaimDelay = 1 days;
        r.metrics.totalClaimDelay = 2 days;
        (score,,) = board.previewScore(r.metrics, r.tokens);
        assertEq(score, 3950 + 1450);
        r.metrics.totalClaimDelay = 2 days + 1;
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
        // A sum below the maximum is impossible: the maximum is one of the summands.
        r.metrics.totalClaimDelay = 1 days - 1;
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
        // The window is the largest reportable maximum; one second over is rejected even with a valid sum.
        r.metrics.maxClaimDelay = window + 1;
        r.metrics.totalClaimDelay = 2 * (window + 1);
        vm.expectRevert(Board.InvalidMetrics.selector);
        board.previewScore(r.metrics, r.tokens);
    }

    /// forge-config: default.fuzz.runs = 1000
    function testFuzzTotalDelayAcceptedIffBetweenMaxAndClaimsTimesMax(uint8 claimsSeed, uint64 maxSeed, uint64 total)
        public
    {
        uint32 claims = uint32(bound(claimsSeed, 1, 20));
        uint64 max = uint64(bound(maxSeed, 0, board.CLAIM_WINDOW()));
        Board.WalletReport memory r = _report(alice, 1, 0);
        r.metrics.eligibleClaims = claims;
        r.metrics.claimedClaims = claims;
        r.metrics.maxClaimDelay = max;
        r.metrics.totalClaimDelay = total;
        bool valid = total >= max && total <= uint64(claims) * max;
        if (!valid) vm.expectRevert(Board.InvalidMetrics.selector);
        (uint16 score,,) = board.previewScore(r.metrics, r.tokens);
        if (valid) {
            // Independent oracle for the speed term; the other four terms are fixed by _report at 3950.
            uint256 expected = 1500 * (uint256(30 days) * claims - total) / (uint256(30 days) * claims);
            assertEq(score, 3950 + expected);
        }
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
            // Delays are capped per claim at CLAIM_WINDOW by the indexer; the window itself is a valid value.
            uint64 maxDelay = uint64(s % (30 days + 1));
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
