"""SQLite persistence: raw events, checkpoints, run log and immutable snapshots.

Raw transfer events are stored separately from derived snapshot metrics. Every
event row is unique on (tx_hash, log_index), so re-processing a block range is
idempotent and can never duplicate an event.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  stream TEXT PRIMARY KEY,          -- e.g. transfers:<token>, seats:<nft>
  block_number INTEGER NOT NULL,    -- last fully indexed block
  block_hash TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
  number INTEGER PRIMARY KEY,
  hash TEXT NOT NULL,
  timestamp INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_events (
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL,
  block_number INTEGER NOT NULL,
  block_hash TEXT NOT NULL,
  token TEXT NOT NULL,
  from_address TEXT NOT NULL,
  to_address TEXT NOT NULL,
  amount TEXT NOT NULL,             -- decimal string, native token units
  PRIMARY KEY (tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS transfer_events_order ON transfer_events(token, block_number, log_index);
CREATE INDEX IF NOT EXISTS transfer_events_from ON transfer_events(from_address);
CREATE INDEX IF NOT EXISTS transfer_events_to ON transfer_events(to_address);

CREATE TABLE IF NOT EXISTS seat_events (
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL,
  block_number INTEGER NOT NULL,
  block_hash TEXT NOT NULL,
  nft TEXT NOT NULL,
  kind TEXT NOT NULL,               -- transfer | activation
  seat_id TEXT,                     -- decimal string
  from_address TEXT,
  to_address TEXT,
  wallet TEXT,
  PRIMARY KEY (tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS seat_events_order ON seat_events(nft, block_number, log_index);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  status TEXT NOT NULL,             -- running | success | failed
  attempt INTEGER NOT NULL DEFAULT 1,
  as_of_block INTEGER,
  snapshot_id TEXT,
  events_added INTEGER NOT NULL DEFAULT 0,
  rpc_requests INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY,              -- S<sequence>-<block>
  sequence INTEGER NOT NULL UNIQUE,
  as_of_block INTEGER NOT NULL,
  as_of_block_hash TEXT NOT NULL,
  as_of_timestamp INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  content_hash TEXT NOT NULL,       -- sha256 of the canonical wallet rows
  score_version TEXT NOT NULL,
  total_seats INTEGER,
  activated_seats INTEGER,
  ranked_wallets INTEGER NOT NULL,
  metadata TEXT NOT NULL            -- JSON: config, data-quality flags, token facts
);

CREATE TABLE IF NOT EXISTS snapshot_wallets (
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
  rank INTEGER NOT NULL,
  wallet TEXT NOT NULL,
  score INTEGER NOT NULL,
  tier INTEGER NOT NULL,
  components TEXT NOT NULL,         -- JSON breakdown
  seat_status TEXT NOT NULL,        -- activated | holder | none | unknown
  seat_count INTEGER NOT NULL,
  first_seat_seen_at INTEGER,
  first_activation_at INTEGER,
  first_acquired_at INTEGER,
  first_acquired_block INTEGER,
  balance TEXT NOT NULL,
  balance_verified INTEGER NOT NULL, -- 1 verified by balanceOf at as-of block, 0 derived only, -1 mismatch
  onchain_balance TEXT,
  total_received TEXT NOT NULL,
  total_sent TEXT NOT NULL,
  transfers_in INTEGER NOT NULL,
  transfers_out INTEGER NOT NULL,
  current_hold_seconds INTEGER NOT NULL,
  current_hold_since INTEGER,
  longest_hold_seconds INTEGER NOT NULL,
  retained_all INTEGER NOT NULL,     -- balance == total received
  never_sent_after_first INTEGER NOT NULL,
  held_continuously INTEGER NOT NULL, -- nonzero balance since first acquisition
  retention_ratio_bps INTEGER NOT NULL,
  retention_ratio TEXT NOT NULL,
  last_outgoing_at INTEGER,
  PRIMARY KEY (snapshot_id, rank),
  UNIQUE (snapshot_id, wallet)
);
CREATE INDEX IF NOT EXISTS snapshot_wallets_wallet ON snapshot_wallets(wallet);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_checkpoint(conn: sqlite3.Connection, stream: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM checkpoints WHERE stream = ?", (stream,)).fetchone()


def set_checkpoint(conn: sqlite3.Connection, stream: str, block_number: int, block_hash: str) -> None:
    conn.execute(
        "INSERT INTO checkpoints(stream, block_number, block_hash, updated_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(stream) DO UPDATE SET block_number = excluded.block_number, block_hash = excluded.block_hash, updated_at = excluded.updated_at",
        (stream, block_number, block_hash, int(time.time())),
    )


def start_run(conn: sqlite3.Connection, attempt: int) -> int:
    cur = conn.execute("INSERT INTO runs(started_at, status, attempt) VALUES(?, 'running', ?)", (int(time.time()), attempt))
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, **fields) -> None:
    columns = ", ".join(f"{k} = ?" for k in fields)
    sql = f"UPDATE runs SET finished_at = ?, status = ?{', ' + columns if columns else ''} WHERE id = ?"
    conn.execute(sql, (int(time.time()), status, *fields.values(), run_id))


def last_successful_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE status = 'success' ORDER BY finished_at DESC, id DESC LIMIT 1").fetchone()


def latest_snapshot(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM snapshots ORDER BY sequence DESC LIMIT 1").fetchone()


def snapshot_row(row: sqlite3.Row) -> dict:
    return {
        "snapshotId": row["id"],
        "sequence": row["sequence"],
        "asOfBlock": row["as_of_block"],
        "asOfBlockHash": row["as_of_block_hash"],
        "asOfTimestamp": row["as_of_timestamp"],
        "asOfIso": _iso(row["as_of_timestamp"]),
        "createdAt": row["created_at"],
        "createdAtIso": _iso(row["created_at"]),
        "contentHash": row["content_hash"],
        "scoreVersion": row["score_version"],
        "totalSeats": row["total_seats"],
        "activatedSeats": row["activated_seats"],
        "rankedWallets": row["ranked_wallets"],
        "metadata": json.loads(row["metadata"]),
    }


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
