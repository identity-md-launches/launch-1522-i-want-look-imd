// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {IMDChadBoard as Board} from "../src/IMDChadBoard.sol";

/// @notice Drives the board through random begin / append / finalize / abort / configure / attack sequences.
contract BoardHandler is Test {
    Board internal immutable board;
    address internal immutable owner;
    address internal immutable reporter;
    address internal immutable nft;
    address internal immutable token;
    address internal constant STRANGER = address(0xBAD);

    // Planned rows for the pending epoch, already sorted in ranking order.
    Board.WalletReport[] internal _plan;
    uint256 internal _planned;
    uint256 internal _appended;

    // Ghosts.
    uint64[] public published;
    mapping(uint64 => bytes32) public publishedDigest;
    uint256 public unauthorizedSuccesses;
    uint256 public invalidAppendSuccesses;
    uint256 public configChangedMidEpoch;
    uint256 public finalizedCount;
    uint256 public abortedCount;

    constructor(Board board_, address owner_, address reporter_, address nft_, address token_) {
        board = board_;
        owner = owner_;
        reporter = reporter_;
        nft = nft_;
        token = token_;
    }

    function publishedLength() external view returns (uint256) {
        return published.length;
    }

    function begin(uint256 seed) external {
        if (board.pendingEpoch() != 0) return;
        vm.roll(vm.getBlockNumber() + 20 + seed % 300);
        vm.warp(vm.getBlockTimestamp() + 10 minutes + seed % 1 hours);
        uint256 count = seed % 6; // 0..5 wallets.
        delete _plan;
        uint16[] memory scores = new uint16[](count);
        uint64 seats;
        for (uint256 i; i < count; ++i) {
            Board.WalletReport memory r = _randomReport(address(uint160(0x7000 + (seed >> 8) % 4 + i * 4)), seed, i);
            (scores[i],,) = board.previewScore(r.metrics, r.tokens);
            seats += r.metrics.activeSeats;
            // Insert keeping score descending, address ascending.
            uint256 at = _plan.length;
            _plan.push(r);
            while (
                at > 0
                    && (scores[at] > scores[at - 1]
                        || (scores[at] == scores[at - 1] && _plan[at].wallet < _plan[at - 1].wallet))
            ) {
                (scores[at], scores[at - 1]) = (scores[at - 1], scores[at]);
                Board.WalletReport memory tmp = _plan[at];
                _plan[at] = _plan[at - 1];
                _plan[at - 1] = tmp;
                --at;
            }
        }
        uint64 height = uint64(vm.getBlockNumber() - 1 - seed % 10);
        bytes32 hash = keccak256(abi.encode("block", height));
        vm.setBlockhash(height, hash);
        Board.SnapshotInput memory input = Board.SnapshotInput(
            height,
            uint64(vm.getBlockTimestamp() - seed % 5 minutes),
            hash,
            seats + uint64(seed % 7),
            seats,
            uint32(count),
            keccak256(abi.encode("evidence", seed)),
            board.configuration()
        );
        vm.prank(reporter);
        board.beginEpoch(input);
        _planned = count;
        _appended = 0;
    }

    function append(uint256 batchSeed) external {
        uint64 id = board.pendingEpoch();
        if (id == 0 || _appended == _planned) return;
        uint256 n = 1 + batchSeed % (_planned - _appended);
        Board.WalletReport[] memory batch = new Board.WalletReport[](n);
        for (uint256 i; i < n; ++i) {
            batch[i] = _plan[_appended + i];
        }
        vm.prank(reporter);
        board.appendWallets(id, batch);
        _appended += n;
    }

    function finalize(uint256 lateSeed) external {
        uint64 id = board.pendingEpoch();
        if (id == 0) return;
        vm.prank(reporter);
        try board.finalizeEpoch(id) {
            if (_appended != _planned) ++invalidAppendSuccesses; // Incomplete census published.
            published.push(id);
            publishedDigest[id] = _digest(id);
            ++finalizedCount;
        } catch (bytes memory reason) {
            bytes4 sel = bytes4(reason);
            assertTrue(sel == Board.IncompleteSnapshot.selector || sel == Board.SnapshotTooOld.selector);
            if (sel == Board.IncompleteSnapshot.selector) assertLt(_appended, _planned);
        }
        lateSeed; // silence
    }

    function abort(bool byOwner) external {
        uint64 id = board.pendingEpoch();
        if (id == 0) return;
        vm.prank(byOwner ? owner : reporter);
        board.abortEpoch(id);
        ++abortedCount;
    }

    /// Re-appointing the reporter is the owner's recovery path: it must abort any draft in the same transaction.
    function rotateReporter() external {
        bool pending = board.pendingEpoch() != 0;
        uint64 configBefore = board.configuration();
        vm.prank(owner);
        board.setReporter(reporter);
        if (pending) ++abortedCount;
        assertEq(board.pendingEpoch(), 0);
        assertEq(board.configuration(), configBefore + 1);
    }

    function passTime(uint256 seconds_) external {
        vm.warp(vm.getBlockTimestamp() + bound(seconds_, 0, 3 days));
        vm.roll(vm.getBlockNumber() + 1);
    }

    function reconfigure(uint256 seed) external {
        uint256 kind = seed % 3;
        bool pending = board.pendingEpoch() != 0;
        vm.prank(owner);
        if (kind == 0) {
            try board.setMaxAge(uint64(1 hours + seed % 3 days)) {
                if (pending) ++configChangedMidEpoch;
            } catch {
                assertTrue(pending);
            }
        } else if (kind == 1) {
            try board.setSources(nft, keccak256(abi.encode("methodology", seed))) {
                if (pending) ++configChangedMidEpoch;
            } catch {
                assertTrue(pending);
            }
        } else {
            Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](1);
            policies[0] = Board.TokenPolicy(token, uint128(1 + seed % 500e6));
            try board.setTokenPolicies(policies) {
                if (pending) ++configChangedMidEpoch;
            } catch {
                assertTrue(pending);
            }
        }
    }

    /// Every privileged entry point called by a stranger must fail.
    function strangerAttack(uint256 which) external {
        uint64 id = board.pendingEpoch();
        Board.WalletReport[] memory reports = new Board.WalletReport[](1);
        reports[0] = _randomReport(STRANGER, which, 0);
        Board.SnapshotInput memory input;
        Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](1);
        policies[0] = Board.TokenPolicy(token, 1);
        bool ok;
        vm.startPrank(STRANGER);
        uint256 k = which % 9;
        if (k == 0) (ok,) = address(board).call(abi.encodeCall(Board.appendWallets, (id, reports)));
        else if (k == 1) (ok,) = address(board).call(abi.encodeCall(Board.finalizeEpoch, (id)));
        else if (k == 2) (ok,) = address(board).call(abi.encodeCall(Board.abortEpoch, (id)));
        else if (k == 3) (ok,) = address(board).call(abi.encodeCall(Board.beginEpoch, (input)));
        else if (k == 4) (ok,) = address(board).call(abi.encodeCall(Board.setReporter, (STRANGER)));
        else if (k == 5) (ok,) = address(board).call(abi.encodeCall(Board.setSources, (nft, bytes32(which))));
        else if (k == 6) (ok,) = address(board).call(abi.encodeCall(Board.setTokenPolicies, (policies)));
        else if (k == 7) (ok,) = address(board).call(abi.encodeCall(Board.transferOwnership, (STRANGER)));
        else (ok,) = address(board).call(abi.encodeCall(Board.acceptOwnership, ()));
        vm.stopPrank();
        if (ok) ++unauthorizedSuccesses;
    }

    /// The reporter itself tries malformed appends: duplicates, out-of-order rows, over-count.
    function reporterMisbehaves(uint256 which) external {
        uint64 id = board.pendingEpoch();
        if (id == 0) return;
        Board.WalletReport[] memory reports;
        uint256 k = which % 3;
        if (k == 0) {
            if (_appended == 0) return;
            reports = new Board.WalletReport[](1);
            reports[0] = _plan[_appended - 1]; // Duplicate of a written wallet.
        } else if (k == 1) {
            if (_planned - _appended < 2) return;
            reports = new Board.WalletReport[](2);
            reports[0] = _plan[_appended + 1];
            reports[1] = _plan[_appended]; // Swapped order.
            bool sameRank = reports[0].wallet == reports[1].wallet;
            if (sameRank) return;
        } else {
            reports = new Board.WalletReport[](_planned - _appended + 1);
            for (uint256 i; i < reports.length - 1; ++i) {
                reports[i] = _plan[_appended + i];
            }
            reports[reports.length - 1] = _randomReport(address(0xFFFFFF), which, 9); // One beyond walletCount.
        }
        vm.prank(reporter);
        try board.appendWallets(id, reports) {
            // A swap of two equal-score rows with ascending addresses would be the only valid swap; it cannot
            // happen because the plan is already strictly ordered, so any success is a defect.
            ++invalidAppendSuccesses;
        } catch {}
    }

    function _digest(uint64 id) public view returns (bytes32 d) {
        Board.Epoch memory e = board.getEpoch(id);
        d = keccak256(abi.encode(e));
        Board.Leader[] memory page = board.leaderboard(id, 0, 100);
        for (uint256 i; i < page.length; ++i) {
            d = keccak256(
                abi.encode(d, page[i], board.walletAt(id, page[i].wallet).stats, board.walletTokens(id, page[i].wallet))
            );
        }
        d = keccak256(abi.encode(d, board.epochTokenPolicies(id)));
    }

    function _randomReport(address wallet, uint256 seed, uint256 salt)
        internal
        view
        returns (Board.WalletReport memory r)
    {
        uint256 s = uint256(keccak256(abi.encode(seed, salt, wallet)));
        r.wallet = wallet;
        r.metrics.activeSeats = uint32(1 + s % 3);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.launches = uint32(s % 40);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.eligibleClaims = uint32(s % 4);
        s = uint256(keccak256(abi.encode(s)));
        r.metrics.claimedClaims = r.metrics.eligibleClaims == 0 ? 0 : uint32(s % (r.metrics.eligibleClaims + 1));
        uint256 policies = board.tokenPolicies().length;
        r.tokens = new Board.TokenReport[](policies);
        if (r.metrics.claimedClaims != 0) {
            s = uint256(keccak256(abi.encode(s)));
            uint64 maxDelay = uint64(s % (30 days + 1)); // Capped per claim; the window itself is valid.
            r.metrics.maxClaimDelay = maxDelay;
            r.metrics.totalClaimDelay = maxDelay * r.metrics.claimedClaims;
            s = uint256(keccak256(abi.encode(s)));
            uint128 claimed = uint128(1 + s % 1e9);
            uint128 sold = uint128(s % (claimed + 1));
            uint128 held = claimed - sold;
            r.tokens[0] = Board.TokenReport(claimed, 0, sold, 0, held, sold, 0, held);
        }
        s = uint256(keccak256(abi.encode(s)));
        r.tokens[0].bought = uint128(s % 300e6);
        r.tokens[0].balance += r.tokens[0].bought;
        r.metrics.interactions = uint32(s % 20);
        r.metrics.distinctApps = uint16(r.metrics.interactions / 2);
    }
}

contract IMDChadBoardInvariantTest is Test {
    Board internal board;
    BoardHandler internal handler;
    address internal owner = makeAddr("owner");
    address internal reporter = makeAddr("reporter");
    address internal nft = address(0x1000);
    address internal token = address(0x2000);

    function setUp() public {
        vm.warp(100 days);
        vm.roll(10_000);
        vm.etch(nft, hex"00");
        vm.etch(token, hex"00");
        board = new Board(owner);
        Board.TokenPolicy[] memory policies = new Board.TokenPolicy[](1);
        policies[0] = Board.TokenPolicy(token, 100e6);
        vm.startPrank(owner);
        board.setSources(nft, keccak256("methodology"));
        board.setReporter(reporter);
        board.setTokenPolicies(policies);
        vm.stopPrank();
        handler = new BoardHandler(board, owner, reporter, nft, token);
        targetContract(address(handler));
    }

    /// forge-config: default.invariant.runs = 256
    /// forge-config: default.invariant.depth = 40
    function invariant_pointersReferToCorrectStatus() public view {
        uint64 latest = board.latestEpoch();
        uint64 pending = board.pendingEpoch();
        if (latest != 0) assertEq(uint8(board.getEpoch(latest).status), uint8(Board.Status.Published));
        if (pending != 0) {
            assertEq(uint8(board.getEpoch(pending).status), uint8(Board.Status.Building));
            assertEq(pending, board.epochCount());
            assertGt(pending, latest);
        }
        assertLe(latest, board.epochCount());
        assertEq(board.epochCount(), handler.finalizedCount() + handler.abortedCount() + (pending != 0 ? 1 : 0));
        uint256 n = handler.publishedLength();
        assertEq(latest, n == 0 ? 0 : handler.published(n - 1));
    }

    /// forge-config: default.invariant.runs = 256
    /// forge-config: default.invariant.depth = 40
    function invariant_publishedEpochsAreImmutable() public view {
        uint256 n = handler.publishedLength();
        for (uint256 i; i < n; ++i) {
            uint64 id = handler.published(i);
            assertEq(handler._digest(id), handler.publishedDigest(id));
        }
    }

    /// forge-config: default.invariant.runs = 256
    /// forge-config: default.invariant.depth = 40
    function invariant_publishedCensusIsCompleteAndOrdered() public view {
        uint256 n = handler.publishedLength();
        uint64 lastBlock;
        uint64 lastTime;
        for (uint256 i; i < n; ++i) {
            uint64 id = handler.published(i);
            Board.Epoch memory e = board.getEpoch(id);
            assertEq(e.walletsWritten, e.snapshot.walletCount);
            assertEq(e.seatsWritten, e.snapshot.activatedSeats);
            assertLe(e.snapshot.activatedSeats, e.snapshot.totalSeats);
            assertGt(e.snapshot.blockNumber, lastBlock);
            assertGt(e.snapshot.timestamp, lastTime);
            lastBlock = e.snapshot.blockNumber;
            lastTime = e.snapshot.timestamp;
            Board.Leader[] memory page = board.leaderboard(id, 0, 100);
            assertEq(page.length, e.walletsWritten);
            uint256 seats;
            for (uint256 k; k < page.length; ++k) {
                assertEq(page[k].rank, k + 1);
                assertLe(page[k].score, 10_000);
                assertGt(page[k].activeSeats, 0);
                seats += page[k].activeSeats;
                if (k > 0) {
                    assertTrue(
                        page[k].score < page[k - 1].score
                            || (page[k].score == page[k - 1].score && page[k].wallet > page[k - 1].wallet)
                    );
                }
                Board.Rating memory r = board.walletAt(id, page[k].wallet);
                assertTrue(r.found);
                assertEq(r.stats.rank, k + 1);
                Board.TokenReport[] memory t = board.walletTokens(id, page[k].wallet);
                assertEq(t.length, board.epochTokenPolicies(id).length);
                for (uint256 j; j < t.length; ++j) {
                    assertEq(uint256(t[j].rewardHeld) + t[j].rewardSold + t[j].rewardOtherOut, t[j].claimed);
                    assertLe(t[j].rewardHeld, t[j].balance);
                }
            }
            assertEq(seats, e.seatsWritten);
        }
    }

    /// forge-config: default.invariant.runs = 256
    /// forge-config: default.invariant.depth = 40
    function invariant_noUnauthorizedOrInvalidWriteSucceeds() public view {
        assertEq(handler.unauthorizedSuccesses(), 0);
        assertEq(handler.invalidAppendSuccesses(), 0);
        assertEq(handler.configChangedMidEpoch(), 0);
        assertEq(board.owner(), owner);
        assertEq(board.reporter(), reporter);
        assertEq(address(board).balance, 0);
    }
}
