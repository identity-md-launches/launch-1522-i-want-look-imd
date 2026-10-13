"""Refresh orchestration: index, snapshot, publish, with retries and a run log."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time

from . import db
from .config import Config
from .indexer import sync_seats, sync_transfers
from .rpc import Rpc
from .snapshot import build_snapshot

log = logging.getLogger("chadboard.pipeline")

# keccak256 selectors of the board's public getters, computed with `cast sig`
# (pure-Python keccak is not in the standard library). Checked in service/tests.
SELECTORS = {
    "seatNFT": "0x3a3e7ca4",
    "reporter": "0x010ec441",
    "latestEpoch": "0x9cb118bf",
    "configuration": "0x6c70bee9",
    "methodologyHash": "0xcdd7d5d4",
}


def _selector(signature: str) -> str:
    return SELECTORS[signature]


def read_board_state(rpc: Rpc, cfg: Config, block: int) -> dict:
    state: dict = {"address": cfg.board}
    for name in ("seatNFT", "reporter", "latestEpoch", "configuration", "methodologyHash"):
        try:
            raw = rpc.eth_call(cfg.board, _selector(name), block)
        except Exception as err:  # noqa: BLE001
            state[name] = None
            state.setdefault("errors", []).append(f"{name}: {str(err)[:100]}")
            continue
        word = raw[2:].rjust(64, "0")
        if name in ("seatNFT", "reporter"):
            state[name] = "0x" + word[-40:]
        elif name == "methodologyHash":
            state[name] = "0x" + word
        else:
            state[name] = int(word, 16)
    return state


def resolve_seat_nft(cfg: Config, board_state: dict) -> str:
    onchain = board_state.get("seatNFT")
    if onchain and int(onchain, 16) != 0:
        return onchain.lower()
    return cfg.seat_nft


def refresh_once(conn, rpc: Rpc, cfg: Config, run_id: int) -> dict:
    chain_id = rpc.chain_id()
    if chain_id != cfg.chain_id:
        raise RuntimeError(f"RPC chain id {chain_id} differs from configured {cfg.chain_id}")
    as_of = rpc.finalized_block(cfg.confirmations)
    as_of_block = int(as_of["number"], 16)
    board_state = read_board_state(rpc, cfg, as_of_block)
    nft = resolve_seat_nft(cfg, board_state)
    added = sync_transfers(conn, rpc, cfg, as_of_block)
    if nft:
        added += sync_seats(conn, rpc, cfg, nft, as_of_block)
    # The snapshot's as-of block is the last block fully covered by the transfer checkpoint,
    # so a bounded backfill run still yields a consistent (if provisional) snapshot.
    cp = db.get_checkpoint(conn, f"transfers:{cfg.token}")
    if cp and cp["block_number"] < as_of_block:
        as_of = rpc.block(cp["block_number"])
        as_of_block = cp["block_number"]
    snapshot_id = build_snapshot(conn, rpc, cfg, as_of, nft, board_state)
    publication = write_publication(conn, cfg, snapshot_id, board_state)
    return {"snapshot_id": snapshot_id, "as_of_block": as_of_block, "events_added": added, "publication": publication}


def refresh_with_retries(conn, cfg: Config) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, cfg.retry_attempts + 1):
        run_id = db.start_run(conn, attempt)
        rpc = Rpc(cfg.rpc_urls, timeout=cfg.rpc_timeout, attempts=cfg.rpc_attempts)
        try:
            result = refresh_once(conn, rpc, cfg, run_id)
            db.finish_run(
                conn, run_id, "success",
                as_of_block=result["as_of_block"], snapshot_id=result["snapshot_id"],
                events_added=result["events_added"], rpc_requests=rpc.requests,
            )
            log.info("refresh succeeded: %s", result["snapshot_id"])
            return result
        except Exception as err:  # noqa: BLE001 - every failure is recorded and retried
            last_error = err
            try:
                conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            db.finish_run(conn, run_id, "failed", error=str(err)[:1000], rpc_requests=rpc.requests)
            log.error("refresh attempt %d failed: %s", attempt, err)
            if attempt < cfg.retry_attempts:
                time.sleep(cfg.retry_backoff_seconds * attempt)
    raise RuntimeError(f"refresh failed after {cfg.retry_attempts} attempts: {last_error}")


# Publication in the deployed board's format ---------------------------------

def write_publication(conn, cfg: Config, snapshot_id: str, board_state: dict) -> dict:
    """Write the IMDChadBoard publication payload for this snapshot.

    The board stores SnapshotInput + WalletReport rows. Only the appointed reporter can
    submit them, and the board must be configured by its owner first. The service never
    signs: it emits the exact arguments (and calldata when `cast` is installed) for the
    reporter's own transaction workflow.
    """
    snap = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    wallets = conn.execute("SELECT * FROM snapshot_wallets WHERE snapshot_id = ? ORDER BY rank", (snapshot_id,)).fetchall()
    cfg.publication_dir.mkdir(parents=True, exist_ok=True)
    snapshot_input = {
        "blockNumber": snap["as_of_block"],
        "timestamp": snap["as_of_timestamp"],
        "blockHash": snap["as_of_block_hash"],
        "totalSeats": snap["total_seats"] or 0,
        "activatedSeats": snap["activated_seats"] or 0,
        "walletCount": snap["ranked_wallets"],
        "evidenceHash": "0x" + snap["content_hash"],
        "configuration": board_state.get("configuration") or 0,
    }
    reports = [
        {
            "wallet": w["wallet"],
            "metrics": {
                "activeSeats": w["seat_count"], "launches": 0, "eligibleClaims": 0, "claimedClaims": 0,
                "totalClaimDelay": 0, "maxClaimDelay": 0, "interactions": 0, "distinctApps": 0,
            },
            "tokens": [
                {"claimed": "0", "bought": "0", "sold": "0", "otherOut": w["total_sent"], "rewardHeld": "0",
                 "rewardSold": "0", "rewardOtherOut": "0", "balance": w["balance"]}
            ],
        }
        for w in wallets
    ]
    blockers = []
    if not board_state.get("reporter") or int(board_state["reporter"], 16) == 0:
        blockers.append("board reporter is unset (owner must call setReporter)")
    if not board_state.get("seatNFT") or int(board_state["seatNFT"], 16) == 0:
        blockers.append("board seatNFT is unset (owner must call setSources)")
    if (board_state.get("configuration") or 0) == 0:
        blockers.append("board configuration revision is 0 (token policies unset)")
    if snap["total_seats"] is None:
        blockers.append("seat census unavailable in this snapshot")
    payload = {
        "snapshotId": snapshot_id,
        "board": cfg.board,
        "format": "IMDChadBoard beginEpoch/appendWallets/finalizeEpoch",
        "note": "Launch, claim, purchase and app metrics are zero because no policy sources are configured; the on-chain score for these rows would reflect seats and balances only.",
        "submittable": not blockers,
        "blockers": blockers,
        "beginEpoch": snapshot_input,
        "appendWallets": [reports[i : i + 20] for i in range(0, len(reports), 20)],
        "finalizeEpoch": "epoch id returned by beginEpoch",
        "calldata": None,
    }
    cast = shutil.which("cast")
    if cast and not blockers:
        try:
            payload["calldata"] = {"beginEpoch": _cast_calldata(cast, snapshot_input)}
        except Exception as err:  # noqa: BLE001
            payload["calldataError"] = str(err)[:300]
    path = cfg.publication_dir / f"{snapshot_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    return {"path": str(path), "submittable": payload["submittable"], "blockers": blockers}


def _cast_calldata(cast: str, s: dict) -> str:
    tuple_arg = f"({s['blockNumber']},{s['timestamp']},{s['blockHash']},{s['totalSeats']},{s['activatedSeats']},{s['walletCount']},{s['evidenceHash']},{s['configuration']})"
    out = subprocess.run(
        [cast, "calldata", "beginEpoch((uint64,uint64,bytes32,uint64,uint64,uint32,bytes32,uint64))", tuple_arg],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return out.stdout.strip()
