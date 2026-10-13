"""Chunked, checkpointed, idempotent log indexing for the IMD token and the seat NFT."""

from __future__ import annotations

import logging
import sqlite3

from . import db
from .config import ERC20_TRANSFER_TOPIC, Config
from .rpc import Rpc

log = logging.getLogger("chadboard.indexer")

REORG_REWIND = 256  # blocks removed when a checkpoint hash no longer matches the chain


def topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def find_deploy_block(rpc: Rpc, address: str, upper: int) -> int:
    """Binary-search the first block at which the address has code."""
    lo, hi = 0, upper
    if rpc.get_code(address, upper) in ("0x", "", None):
        raise RuntimeError(f"{address} has no code at block {upper}")
    while lo < hi:
        mid = (lo + hi) // 2
        if rpc.get_code(address, mid) not in ("0x", "", None):
            hi = mid
        else:
            lo = mid + 1
    return lo


def _ensure_checkpoint(conn: sqlite3.Connection, rpc: Rpc, stream: str, address: str, start_block: int, head: int) -> int:
    """Return the first block that still needs indexing, rewinding on a reorg."""
    cp = db.get_checkpoint(conn, stream)
    if cp is None:
        first = start_block if start_block > 0 else find_deploy_block(rpc, address, head)
        prev = max(first - 1, 0)
        block = rpc.block(prev)
        db.set_checkpoint(conn, stream, prev, block["hash"])
        log.info("%s: starting at block %d", stream, first)
        return first
    chain_hash = rpc.block(cp["block_number"])["hash"]
    if chain_hash.lower() == cp["block_hash"].lower():
        return cp["block_number"] + 1
    rewind_to = max(cp["block_number"] - REORG_REWIND, 0)
    log.warning("%s: checkpoint %d hash mismatch, rewinding to %d", stream, cp["block_number"], rewind_to)
    table = "transfer_events" if stream.startswith("transfers:") else "seat_events"
    with conn:
        conn.execute("BEGIN")
        conn.execute(f"DELETE FROM {table} WHERE block_number > ?", (rewind_to,))
        conn.execute("DELETE FROM blocks WHERE number > ?", (rewind_to,))
        db.set_checkpoint(conn, stream, rewind_to, rpc.block(rewind_to)["hash"])
    return rewind_to + 1


def sync_transfers(conn: sqlite3.Connection, rpc: Rpc, cfg: Config, to_block: int) -> int:
    """Index ERC-20 Transfer logs up to and including to_block. Returns rows added."""
    stream = f"transfers:{cfg.token}"
    head = to_block
    start = _ensure_checkpoint(conn, rpc, stream, cfg.token, cfg.start_block, head)
    if cfg.max_blocks_per_run:
        to_block = min(to_block, start + cfg.max_blocks_per_run - 1)
    added = 0
    if start > to_block:
        return 0
    log.info("%s: indexing blocks %d..%d", stream, start, to_block)
    for chunk_from, chunk_to, logs in rpc.get_logs_adaptive(cfg.token, [ERC20_TRANSFER_TOPIC], start, to_block, cfg.log_chunk):
        rows = []
        for entry in logs:
            if entry.get("removed"):
                continue
            topics = entry["topics"]
            if len(topics) != 3:
                continue  # not a standard indexed from/to Transfer
            rows.append(
                (
                    entry["transactionHash"].lower(),
                    int(entry["logIndex"], 16),
                    int(entry["blockNumber"], 16),
                    entry["blockHash"].lower(),
                    cfg.token,
                    topic_address(topics[1]),
                    topic_address(topics[2]),
                    str(int(entry["data"], 16)) if entry["data"] not in ("0x", "") else "0",
                )
            )
        end_hash = rpc.block(chunk_to)["hash"]
        conn.execute("BEGIN")
        try:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO transfer_events(tx_hash, log_index, block_number, block_hash, token, from_address, to_address, amount) VALUES(?,?,?,?,?,?,?,?)",
                rows,
            )
            added += conn.total_changes - before
            db.set_checkpoint(conn, stream, chunk_to, end_hash)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        log.info("%s: %d..%d  %d logs (%d new)", stream, chunk_from, chunk_to, len(rows), added)
    return added


def sync_seats(conn: sqlite3.Connection, rpc: Rpc, cfg: Config, nft: str, to_block: int) -> int:
    """Index ERC-721 Transfer logs (and optional activation logs) for the seat NFT."""
    stream = f"seats:{nft}"
    start = _ensure_checkpoint(conn, rpc, stream, nft, 0, to_block)
    if cfg.max_blocks_per_run:
        to_block = min(to_block, start + cfg.max_blocks_per_run - 1)
    if start > to_block:
        return 0
    spec = cfg.activation_spec()
    topics: list = [[ERC20_TRANSFER_TOPIC] + ([spec["topic0"]] if spec and spec["topic0"] != ERC20_TRANSFER_TOPIC else [])]
    added = 0
    log.info("%s: indexing blocks %d..%d", stream, start, to_block)
    for chunk_from, chunk_to, logs in rpc.get_logs_adaptive(nft, topics, start, to_block, cfg.log_chunk):
        rows = []
        for entry in logs:
            if entry.get("removed"):
                continue
            t = entry["topics"]
            base = (entry["transactionHash"].lower(), int(entry["logIndex"], 16), int(entry["blockNumber"], 16), entry["blockHash"].lower(), nft)
            if t[0].lower() == ERC20_TRANSFER_TOPIC and len(t) == 4:
                rows.append(base + ("transfer", str(int(t[3], 16)), topic_address(t[1]), topic_address(t[2]), None))
            elif spec and t[0].lower() == spec["topic0"]:
                if "wallet_topic" in spec and len(t) > spec["wallet_topic"]:
                    rows.append(base + ("activation", None, None, None, topic_address(t[spec["wallet_topic"]])))
                elif "seat_topic" in spec and len(t) > spec["seat_topic"]:
                    rows.append(base + ("activation", str(int(t[spec["seat_topic"]], 16)), None, None, None))
        end_hash = rpc.block(chunk_to)["hash"]
        conn.execute("BEGIN")
        try:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO seat_events(tx_hash, log_index, block_number, block_hash, nft, kind, seat_id, from_address, to_address, wallet) VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            added += conn.total_changes - before
            db.set_checkpoint(conn, stream, chunk_to, end_hash)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        log.info("%s: %d..%d  %d logs (%d new)", stream, chunk_from, chunk_to, len(rows), added)
    return added


def ensure_block_timestamps(conn: sqlite3.Connection, rpc: Rpc, numbers: set[int]) -> dict[int, int]:
    """Fetch and cache timestamps for the given block numbers."""
    out: dict[int, int] = {}
    missing = []
    for n in numbers:
        row = conn.execute("SELECT timestamp FROM blocks WHERE number = ?", (n,)).fetchone()
        if row:
            out[n] = row["timestamp"]
        else:
            missing.append(n)
    for n in sorted(missing):
        block = rpc.block(n)
        ts = int(block["timestamp"], 16)
        conn.execute("INSERT OR REPLACE INTO blocks(number, hash, timestamp) VALUES(?,?,?)", (n, block["hash"].lower(), ts))
        out[n] = ts
    return out
