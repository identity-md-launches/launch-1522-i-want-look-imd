"""Derive wallet metrics from raw events and store an immutable, versioned snapshot."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field

from . import db
from .config import SCORE_VERSION, YEAR_SECONDS, Config
from .indexer import ensure_block_timestamps
from .rpc import Rpc

log = logging.getLogger("chadboard.snapshot")
ZERO = "0x" + "0" * 40
BALANCE_OF_SELECTOR = "0x70a08231"


@dataclass
class WalletState:
    balance: int = 0
    total_in: int = 0
    total_out: int = 0
    n_in: int = 0
    n_out: int = 0
    first_in_block: int | None = None
    first_in_index: int | None = None
    last_out_block: int | None = None
    out_after_first: bool = False
    streak_start_block: int | None = None
    streak_started_at_first: bool = False
    longest_streak: int = 0          # seconds, closed streaks only (resolved later)
    closed_streaks: list = field(default_factory=list)  # (start_block, end_block)
    dropped_to_zero: bool = False


def tier_for(score: int) -> int:
    return 3 if score >= 7500 else 2 if score >= 5000 else 1 if score >= 2500 else 0


def score_components(m: dict, cfg: Config) -> dict:
    received = m["total_received"]
    balance = m["balance"]
    retention = (3000 * min(balance, received)) // received if received > 0 else 0
    current_hold = (2000 * min(m["current_hold_seconds"], YEAR_SECONDS)) // YEAR_SECONDS
    longest_hold = (1000 * min(m["longest_hold_seconds"], YEAR_SECONDS)) // YEAR_SECONDS
    never_out = 1500 if (m["never_sent_after_first"] and received > 0) else 0
    size = (1500 * min(balance, cfg.support_target)) // cfg.support_target if cfg.support_target > 0 else 0
    seat = 1000 if m["seat_status"] == "activated" else 0
    components = {
        "retention": retention,
        "currentHolding": current_hold,
        "longestHolding": longest_hold,
        "neverTransferredOut": never_out,
        "balanceSize": size,
        "activatedSeat": seat,
    }
    components["total"] = sum(components.values())
    return components


def replay_transfers(conn: sqlite3.Connection, token: str, as_of_block: int) -> dict[str, WalletState]:
    states: dict[str, WalletState] = {}
    cur = conn.execute(
        "SELECT block_number, log_index, from_address, to_address, amount FROM transfer_events "
        "WHERE token = ? AND block_number <= ? ORDER BY block_number, log_index",
        (token, as_of_block),
    )
    for block, index, src, dst, amount_text in cur:
        amount = int(amount_text)
        if src != ZERO:
            s = states.setdefault(src, WalletState())
            s.total_out += amount
            s.n_out += 1
            s.last_out_block = block
            if s.first_in_block is not None:
                s.out_after_first = True
            s.balance -= amount
            if s.balance <= 0 and s.streak_start_block is not None:
                s.closed_streaks.append((s.streak_start_block, block))
                s.streak_start_block = None
                s.dropped_to_zero = True
        if dst != ZERO:
            d = states.setdefault(dst, WalletState())
            d.total_in += amount
            d.n_in += 1
            if d.first_in_block is None:
                d.first_in_block, d.first_in_index = block, index
            was_zero = d.balance <= 0
            d.balance += amount
            if was_zero and d.balance > 0 and amount > 0:
                d.streak_start_block = block
                d.streak_started_at_first = d.first_in_block == block and not d.dropped_to_zero
    return states


def seat_census(conn: sqlite3.Connection, nft: str, as_of_block: int, spec: dict | None):
    owners: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    activated_wallets: dict[str, int] = {}
    activated_seats: set[str] = set()
    cur = conn.execute(
        "SELECT block_number, kind, seat_id, from_address, to_address, wallet FROM seat_events WHERE nft = ? AND block_number <= ? ORDER BY block_number, log_index",
        (nft, as_of_block),
    )
    for block, kind, seat_id, _src, dst, wallet in cur:
        if kind == "transfer":
            if dst == ZERO:
                owners.pop(seat_id, None)
            else:
                owners[seat_id] = dst
                first_seen.setdefault(dst, block)
        elif kind == "activation":
            if wallet:
                activated_wallets.setdefault(wallet, block)
            elif seat_id is not None:
                activated_seats.add(seat_id)
    seats_by_wallet: dict[str, list[str]] = {}
    for seat_id, owner in owners.items():
        seats_by_wallet.setdefault(owner, []).append(seat_id)
    activated_by_wallet: dict[str, int] = {}
    if spec and "wallet_topic" in spec:
        for wallet, seats in seats_by_wallet.items():
            if wallet in activated_wallets:
                activated_by_wallet[wallet] = len(seats)
    elif spec and "seat_topic" in spec:
        for wallet, seats in seats_by_wallet.items():
            n = sum(1 for s in seats if s in activated_seats)
            if n:
                activated_by_wallet[wallet] = n
                activated_wallets.setdefault(wallet, first_seen.get(wallet, 0))
    return {
        "total_seats": len(owners),
        "seats_by_wallet": seats_by_wallet,
        "first_seen": first_seen,
        "activated_by_wallet": activated_by_wallet,
        "activation_block": activated_wallets,
        "activated_seats": sum(activated_by_wallet.values()),
        "owners": owners,
        "active_seat_ids": activated_seats if spec and "seat_topic" in spec else {s for s, w in owners.items() if w in activated_wallets},
    }


def verify_balance(rpc: Rpc, token: str, wallet: str, block: int) -> int | None:
    try:
        data = BALANCE_OF_SELECTOR + wallet[2:].rjust(64, "0")
        result = rpc.eth_call(token, data, block)
        return int(result, 16) if result not in ("0x", "") else 0
    except Exception as err:  # noqa: BLE001 - verification is best effort and reported as such
        log.warning("balanceOf(%s) failed: %s", wallet, str(err)[:120])
        return None


def build_snapshot(conn: sqlite3.Connection, rpc: Rpc, cfg: Config, as_of: dict, nft: str, board_state: dict) -> str:
    as_of_block = int(as_of["number"], 16)
    as_of_ts = int(as_of["timestamp"], 16)
    as_of_hash = as_of["hash"].lower()
    spec = cfg.activation_spec()
    states = replay_transfers(conn, cfg.token, as_of_block)
    quality: dict = {"notes": []}

    census = None
    if nft:
        census = seat_census(conn, nft, as_of_block, spec)
        if spec:
            universe = {w: "activated" for w in census["activated_by_wallet"]}
            quality["seatCensus"] = "activated seats derived from configured activation events"
        else:
            universe = {w: "holder" for w in census["seats_by_wallet"]}
            quality["seatCensus"] = "activation events not configured; every current seat holder is ranked with seatStatus=holder"
            quality["notes"].append("activation unverified: set CHADBOARD_ACTIVATION_EVENT to distinguish activated seats")
    else:
        universe = {w: "unknown" for w, s in states.items() if s.balance > 0}
        quality["seatCensus"] = "unavailable: the board's seatNFT source is unset and CHADBOARD_SEAT_NFT is empty; ranking every wallet with a nonzero indexed IMD balance"
        quality["notes"].append("seat status unknown for every wallet until the seat NFT is configured")

    # Block timestamps: exact for the blocks that matter, cached in the blocks table.
    needed: set[int] = {as_of_block}
    for w in universe:
        s = states.get(w)
        if not s:
            continue
        for b in (s.first_in_block, s.streak_start_block, s.last_out_block):
            if b is not None:
                needed.add(b)
        for a, b in s.closed_streaks:
            needed.update((a, b))
    if census:
        for w in universe:
            if w in census["first_seen"]:
                needed.add(census["first_seen"][w])
            if w in census["activation_block"]:
                needed.add(census["activation_block"][w])
    stamps = ensure_block_timestamps(conn, rpc, needed)

    rows = []
    for wallet, seat_status in universe.items():
        s = states.get(wallet, WalletState())
        current_since = stamps.get(s.streak_start_block) if s.streak_start_block is not None and s.balance > 0 else None
        current_hold = as_of_ts - current_since if current_since is not None else 0
        longest = current_hold
        for a, b in s.closed_streaks:
            longest = max(longest, stamps[b] - stamps[a])
        received, sent, balance = s.total_in, s.total_out, max(s.balance, 0)
        ratio_bps = (balance * 10000) // received if received > 0 else 0
        m = {
            "wallet": wallet,
            "seat_status": seat_status,
            "seat_count": census["activated_by_wallet"].get(wallet, 0) if census and spec else (len(census["seats_by_wallet"].get(wallet, [])) if census else 0),
            "first_seat_seen_at": stamps.get(census["first_seen"].get(wallet)) if census else None,
            "first_activation_at": stamps.get(census["activation_block"].get(wallet)) if census and wallet in census["activation_block"] else None,
            "first_acquired_at": stamps.get(s.first_in_block) if s.first_in_block is not None else None,
            "first_acquired_block": s.first_in_block,
            "balance": balance,
            "total_received": received,
            "total_sent": sent,
            "transfers_in": s.n_in,
            "transfers_out": s.n_out,
            "current_hold_seconds": current_hold,
            "current_hold_since": current_since,
            "longest_hold_seconds": longest,
            "retained_all": received > 0 and balance == received,
            "never_sent_after_first": received > 0 and not s.out_after_first,
            "held_continuously": received > 0 and balance > 0 and s.streak_started_at_first and not s.dropped_to_zero,
            "retention_ratio_bps": min(ratio_bps, 10000),
            "retention_ratio": f"{balance / received:.6f}" if received > 0 else "0",
            "last_outgoing_at": stamps.get(s.last_out_block) if s.last_out_block is not None else None,
        }
        comps = score_components(m, cfg)
        m["components"] = comps
        m["score"] = comps["total"]
        m["tier"] = tier_for(comps["total"])
        rows.append(m)

    rows.sort(key=lambda r: (-r["score"], int(r["wallet"], 16)))

    verified = 0
    mismatches = 0
    for r in rows[: max(cfg.verify_balances, 0)]:
        onchain = verify_balance(rpc, cfg.token, r["wallet"], as_of_block)
        r["onchain_balance"] = onchain
        if onchain is None:
            r["balance_verified"] = 0
        elif onchain == r["balance"]:
            r["balance_verified"] = 1
            verified += 1
        else:
            r["balance_verified"] = -1
            mismatches += 1
    for r in rows[max(cfg.verify_balances, 0):]:
        r["onchain_balance"] = None
        r["balance_verified"] = 0
    quality["balancesVerifiedOnChain"] = verified
    quality["balanceMismatches"] = mismatches
    if mismatches:
        quality["notes"].append("balance mismatches are kept with balanceVerified=-1; the indexed history may be incomplete for those wallets")
    quality["soldClassification"] = "not attempted: outgoing transfers are reported as transfers, never inferred as sales"
    cp = db.get_checkpoint(conn, f"transfers:{cfg.token}")
    from .backfill import coverage
    history = coverage(conn, cfg, as_of_block)
    stream = f"transfers:{cfg.token}"
    origin_verified = db.get_setting(conn, stream + ":originVerified") == "1"
    target = int(db.get_setting(conn, stream + ":target", str(as_of_block)))
    quality["historyCompleteAtAsOfBlock"] = bool(origin_verified and history["coverageVerified"])
    quality["transferHistoryComplete"] = bool(quality["historyCompleteAtAsOfBlock"] and cp and cp["block_number"] >= target)
    quality["historicalStartBlock"] = history["historicalStartBlock"]
    quality["backfillTargetBlock"] = target
    quality["historyGaps"] = history["gaps"]
    if not quality["transferHistoryComplete"]:
        quality["notes"].append(f"transfer history is provisional: checkpoint {cp['block_number'] if cp else 'none'}, target {target}; verify deployment origin and range coverage")

    canonical = json.dumps(
        [{k: (str(v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in r.items() if k != "onchain_balance"} for r in rows],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    content_hash = hashlib.sha256(canonical).hexdigest()

    seq_row = conn.execute("SELECT COALESCE(MAX(sequence), 0) AS n FROM snapshots").fetchone()
    sequence = int(seq_row["n"]) + 1
    snapshot_id = f"S{sequence}-{as_of_block}"
    metadata = {
        "rankingAuthority": "ethereum",
        "radarAffectsRanking": False,
        "chainId": cfg.chain_id,
        "token": cfg.token,
        "board": cfg.board,
        "seatNFT": nft or None,
        "activationEvent": cfg.activation_event or None,
        "supportTarget": str(cfg.support_target),
        "scoreVersion": SCORE_VERSION,
        "scoreMaximums": {"retention": 3000, "currentHolding": 2000, "longestHolding": 1000, "neverTransferredOut": 1500, "balanceSize": 1500, "activatedSeat": 1000},
        "board_state": board_state,
        "dataQuality": quality,
        "transferEventsIndexed": conn.execute("SELECT COUNT(*) AS n FROM transfer_events WHERE token = ?", (cfg.token,)).fetchone()["n"],
    }
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO snapshots(id, sequence, as_of_block, as_of_block_hash, as_of_timestamp, created_at, content_hash, score_version, total_seats, activated_seats, ranked_wallets, metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id,
                sequence,
                as_of_block,
                as_of_hash,
                as_of_ts,
                int(time.time()),
                content_hash,
                SCORE_VERSION,
                census["total_seats"] if census else None,
                census["activated_seats"] if census and spec else None,
                len(rows),
                json.dumps(metadata),
            ),
        )
        conn.executemany(
            "INSERT INTO snapshot_wallets(snapshot_id, rank, wallet, score, tier, components, seat_status, seat_count, first_seat_seen_at, first_activation_at, first_acquired_at, first_acquired_block, balance, balance_verified, onchain_balance, total_received, total_sent, transfers_in, transfers_out, current_hold_seconds, current_hold_since, longest_hold_seconds, retained_all, never_sent_after_first, held_continuously, retention_ratio_bps, retention_ratio, last_outgoing_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    snapshot_id, i + 1, r["wallet"], r["score"], r["tier"], json.dumps(r["components"]), r["seat_status"], r["seat_count"],
                    r["first_seat_seen_at"], r["first_activation_at"], r["first_acquired_at"], r["first_acquired_block"], str(r["balance"]),
                    r["balance_verified"], str(r["onchain_balance"]) if r["onchain_balance"] is not None else None, str(r["total_received"]),
                    str(r["total_sent"]), r["transfers_in"], r["transfers_out"], r["current_hold_seconds"], r["current_hold_since"],
                    r["longest_hold_seconds"], int(r["retained_all"]), int(r["never_sent_after_first"]), int(r["held_continuously"]),
                    r["retention_ratio_bps"], r["retention_ratio"], r["last_outgoing_at"],
                )
                for i, r in enumerate(rows)
            ],
        )
        if census:
            conn.executemany("INSERT INTO snapshot_seats VALUES(?,?,?,?)", [
                (snapshot_id, seat_id, owner, int(seat_id in census["active_seat_ids"]) if spec else None)
                for seat_id, owner in census["owners"].items()
            ])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    log.info("snapshot %s stored: %d wallets, block %d", snapshot_id, len(rows), as_of_block)
    return snapshot_id
