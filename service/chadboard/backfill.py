"""Archive capability preflight, bounded dry-run and exact resumable coverage reports."""
from __future__ import annotations

import json
import math
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from . import db
from .config import Config, ERC20_TRANSFER_TOPIC
from .indexer import find_deploy_block, sync_transfers
from .rpc import HistoricalRpc, RpcError


def preflight(cfg: Config, end_block: int | None = None) -> dict:
    if not cfg.archive_rpc_url:
        raise RuntimeError("ETH_ARCHIVE_RPC_URL is not set; no archive requests were made")
    rpc = HistoricalRpc(cfg)
    if rpc.chain_id() != cfg.chain_id:
        raise RuntimeError("unexpected Ethereum chain id")
    end = end_block if end_block is not None else int(rpc.finalized_block(cfg.confirmations)["number"], 16)
    rpc.historical_before = end + 1  # All explicit preflight block reads are historical.
    started = time.monotonic()
    start = find_deploy_block(rpc, cfg.token, end)
    historical = rpc.block(start)
    # Probe separated historical windows, including deployment and the intended end.
    probes = []
    event_ids, wallets = set(), set()
    effective_chunk = cfg.log_chunk
    for anchor in sorted({start, start + (end-start)//4, start + (end-start)//2, start + 3*(end-start)//4, end}):
        first = max(start, end-effective_chunk+1) if anchor == end else anchor
        last = min(end, first + effective_chunk - 1)
        try:
            logs = rpc._get_logs_once([{"address": cfg.token, "topics": [ERC20_TRANSFER_TOPIC], "fromBlock": hex(first), "toBlock": hex(last)}])
        except RpcError as err:
            if not err.max_range:
                raise
            effective_chunk = min(effective_chunk, err.max_range)
            last = min(end, first + effective_chunk - 1)
            logs = rpc._get_logs_once([{"address": cfg.token, "topics": [ERC20_TRANSFER_TOPIC], "fromBlock": hex(first), "toBlock": hex(last)}])
        count = len(logs)
        for event in logs:
            event_ids.add((event["transactionHash"], event["logIndex"]))
            for topic in event["topics"][1:3]:
                if int(topic, 16):
                    wallets.add("0x" + topic[-40:].lower())
        probes.append({"fromBlock": first, "toBlock": last, "events": count})
    # Use the real indexer in an isolated DB before any full-history mutation.
    with tempfile.TemporaryDirectory(prefix="chadboard-dry-run-") as tmp:
        conn = db.connect(Path(tmp) / "dry.sqlite")
        dry_end = min(end, start + min(10000, effective_chunk * 2) - 1)
        dry_cfg = replace(cfg, start_block=start, max_blocks_per_run=0, log_chunk=effective_chunk)
        before = rpc.total_requests
        dry_start = time.monotonic()
        count = sync_transfers(conn, rpc, dry_cfg, dry_end)
        elapsed = time.monotonic() - dry_start
        requests = rpc.total_requests - before
        again = sync_transfers(conn, rpc, dry_cfg, dry_end)
        dry = {"startBlock": start, "endBlock": dry_end, "eventCount": count,
               "rpcRequests": requests, "seconds": round(elapsed, 3), "resumeAddedEvents": again}
        conn.close()
    chunks = math.ceil((end-start+1) / max(1, effective_chunk))
    mean = (time.monotonic()-started) / max(rpc.total_requests, 1)
    tested_ranges = sorted([(p["fromBlock"], p["toBlock"]) for p in probes] + [(start, dry_end)])
    gaps, cursor = [], start
    for a, b in tested_ranges:
        if a > cursor:
            gaps.append({"fromBlock": cursor, "toBlock": a - 1})
        cursor = max(cursor, b + 1)
    if cursor <= end:
        gaps.append({"fromBlock": cursor, "toBlock": end})
    # Transfer scan is exactly two requests/chunk absent retries: logs + checkpoint hash.
    return {"archiveVariablePresent": True, "chainId": cfg.chain_id, "token": cfg.token,
            "historicalStartBlock": start, "historicalEndBlock": end,
            "historicalBlockTimestamp": int(historical["timestamp"],16), "historicalBlockHash": historical["hash"],
            "historicalAgeBlocks": end-start, "probes": probes, "dryRun": dry,
            "estimate": {"effectiveLogChunk": effective_chunk, "logRequests": chunks, "checkpointBlockRequests": chunks,
                         "transferScanRequests": 2*chunks+1, "transferScanSeconds": round((2*chunks+1)*mean),
                         "additionalSnapshotRequests": "one per uncached timestamp block plus configured balance checks and board reads",
                         "assumptions": "configured chunk size; no provider range shrink or retries. Timestamp work depends on actual wallet/event count."},
            "preflightRequests": rpc.total_requests, "preflightSeconds": round(time.monotonic()-started,3),
            "verifiedAt": int(time.time()), "sampledEventCount": len(event_ids), "sampledWalletCount": len(wallets),
            "fullBackfillComplete": False, "gaps": gaps,
            "countScope": "non-overlapping probe windows only, not whole-history totals; dry-run uses an isolated database"}


def coverage(conn, cfg: Config, end: int | None = None) -> dict:
    stream = f"transfers:{cfg.token}"
    cp = db.get_checkpoint(conn, stream)
    start = db.get_setting(conn, stream + ":start")
    first = int(start) if start is not None else None
    last = end if end is not None else (cp["block_number"] if cp else None)
    ranges = conn.execute("SELECT from_block,to_block FROM indexed_ranges WHERE stream=? ORDER BY from_block", (stream,)).fetchall()
    gaps = []
    cursor = first
    if first is not None and last is not None:
        for a, b in ranges:
            if b < cursor or a > last:
                continue
            if a > cursor:
                gaps.append({"fromBlock": cursor, "toBlock": min(a-1,last)})
            cursor = max(cursor, b+1)
        if cursor <= last:
            gaps.append({"fromBlock": cursor, "toBlock": last})
    events = conn.execute("SELECT COUNT(*) FROM transfer_events WHERE token=? AND block_number<=?", (cfg.token, last or 0)).fetchone()[0]
    wallets = conn.execute("SELECT COUNT(*) FROM (SELECT from_address a FROM transfer_events WHERE token=? AND block_number<=? UNION SELECT to_address FROM transfer_events WHERE token=? AND block_number<=?) WHERE a != ?", (cfg.token,last or 0,cfg.token,last or 0,"0x"+"0"*40)).fetchone()[0]
    snap = db.latest_snapshot(conn)
    return {"source": "ethereum", "sourceRetrievedAt": cp["updated_at"] if cp else None,
            "historicalStartBlock": first, "historicalEndBlock": last, "checkpointBlock": cp["block_number"] if cp else None,
            "checkpointHash": cp["block_hash"] if cp else None, "walletCount": wallets,
            "walletCountDefinition": "unique nonzero-address senders or recipients in indexed IMD Transfer history",
            "rankedWalletCount": snap["ranked_wallets"] if snap else None,
            "eventCount": events, "gaps": gaps,
            "coverageVerified": first is not None and last is not None and bool(ranges) and not gaps}
