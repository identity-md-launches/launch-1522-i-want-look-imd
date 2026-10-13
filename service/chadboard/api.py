"""Read-only HTTP query API over the stored snapshots (GET only, JSON, CORS-enabled)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db
from .config import SCORE_VERSION, TIERS, Config

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
TOP_SIZES = (10, 50, 100, 1000)
RANKINGS = {
    "current-holding": ("current_hold_seconds DESC, score DESC, wallet ASC", "longest current continuous IMD holding period"),
    "longest-holding": ("longest_hold_seconds DESC, score DESC, wallet ASC", "longest historical continuous IMD holding period"),
    "balance": ("CAST(balance AS REAL) DESC, LENGTH(balance) DESC, balance DESC, wallet ASC", "highest current IMD balance"),
    "retained-all": ("CAST(balance AS REAL) DESC, wallet ASC", "wallets whose current balance equals total received", "retained_all = 1"),
    "retention-ratio": ("retention_ratio_bps DESC, CAST(balance AS REAL) DESC, wallet ASC", "highest current balance / total received"),
    "never-sent": ("current_hold_seconds DESC, wallet ASC", "no outgoing IMD transfer after first acquisition (from indexed history)", "never_sent_after_first = 1"),
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def wallet_json(row: sqlite3.Row, decimals: int = 18) -> dict:
    def units(text: str | None):
        if text is None:
            return None
        v = int(text)
        return {"raw": text, "formatted": f"{v / 10**decimals:.6f}"}

    return {
        "wallet": row["wallet"],
        "found": True,
        "rank": row["rank"],
        "score": row["score"],
        "tier": row["tier"],
        "tierName": TIERS[row["tier"]],
        "components": json.loads(row["components"]),
        "seat": {
            "status": row["seat_status"],
            "activated": row["seat_status"] == "activated",
            "count": row["seat_count"],
            "firstSeenAt": row["first_seat_seen_at"],
            "firstActivationAt": row["first_activation_at"],
        },
        "balances": {
            "current": units(row["balance"]),
            "totalReceived": units(row["total_received"]),
            "totalSent": units(row["total_sent"]),
            "onChainAtAsOfBlock": units(row["onchain_balance"]),
            "balanceVerified": {1: "verified", 0: "derived-only", -1: "mismatch"}[row["balance_verified"]],
            "transfersIn": row["transfers_in"],
            "transfersOut": row["transfers_out"],
        },
        "holding": {
            "firstAcquiredAt": row["first_acquired_at"],
            "firstAcquiredBlock": row["first_acquired_block"],
            "currentHoldSeconds": row["current_hold_seconds"],
            "currentHoldSince": row["current_hold_since"],
            "longestHoldSeconds": row["longest_hold_seconds"],
            "heldContinuouslySinceFirstAcquisition": bool(row["held_continuously"]),
            "retainedAllReceived": bool(row["retained_all"]),
            "neverSentAfterFirstAcquisition": bool(row["never_sent_after_first"]),
            "retentionRatio": row["retention_ratio"],
            "retentionRatioBps": row["retention_ratio_bps"],
            "lastOutgoingAt": row["last_outgoing_at"],
            "soldStatus": "not-classified",
        },
    }


class Api:
    def __init__(self, conn: sqlite3.Connection, cfg: Config):
        self.conn = conn
        self.cfg = cfg

    # Snapshot helpers ----------------------------------------------------

    def snapshot(self, snapshot_id: str | None) -> dict:
        row = (
            self.conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
            if snapshot_id and snapshot_id != "latest"
            else db.latest_snapshot(self.conn)
        )
        if row is None:
            raise ApiError(404, "no snapshot available yet" if not snapshot_id else f"unknown snapshot {snapshot_id}")
        return db.snapshot_row(row)

    def meta(self, snap: dict) -> dict:
        return {k: snap[k] for k in ("snapshotId", "asOfBlock", "asOfTimestamp", "asOfIso", "scoreVersion", "rankedWallets", "totalSeats", "activatedSeats")}

    # Endpoints -----------------------------------------------------------

    def status(self) -> dict:
        last = db.last_successful_run(self.conn)
        latest = db.latest_snapshot(self.conn)
        last_run = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        cp = db.get_checkpoint(self.conn, f"transfers:{self.cfg.token}")
        return {
            "service": "chadboard-data",
            "scoreVersion": SCORE_VERSION,
            "now": int(time.time()),
            "lastSuccessfulRefresh": last["finished_at"] if last else None,
            "lastSuccessfulRefreshIso": db._iso(last["finished_at"]) if last else None,
            "lastRun": dict(last_run) if last_run else None,
            "refreshIntervalSeconds": self.cfg.interval_seconds,
            "transferCheckpoint": {"block": cp["block_number"], "blockHash": cp["block_hash"], "updatedAt": cp["updated_at"]} if cp else None,
            "transferEventsIndexed": self.conn.execute("SELECT COUNT(*) AS n FROM transfer_events").fetchone()["n"],
            "latestSnapshot": db.snapshot_row(latest) if latest else None,
            "token": self.cfg.token,
            "board": self.cfg.board,
        }

    def snapshots(self) -> dict:
        rows = self.conn.execute("SELECT * FROM snapshots ORDER BY sequence DESC").fetchall()
        return {"snapshots": [db.snapshot_row(r) for r in rows]}

    def wallets(self, addresses: list[str], snapshot_id: str | None) -> dict:
        if not addresses:
            raise ApiError(400, "pass ?addresses=0x...,0x... (1 to 100 wallets)")
        if len(addresses) > 100:
            raise ApiError(400, "at most 100 wallets per request")
        for a in addresses:
            if not ADDRESS_RE.match(a):
                raise ApiError(400, f"invalid address: {a[:60]}")
        snap = self.snapshot(snapshot_id)
        out = []
        for a in addresses:
            row = self.conn.execute("SELECT * FROM snapshot_wallets WHERE snapshot_id = ? AND wallet = ?", (snap["snapshotId"], a.lower())).fetchone()
            out.append(wallet_json(row) if row else {"wallet": a.lower(), "found": False, "rank": 0, "note": "not in this snapshot's ranked set"})
        return {"snapshot": self.meta(snap), "dataQuality": snap["metadata"]["dataQuality"], "wallets": out}

    def leaderboard(self, top: int, snapshot_id: str | None, offset: int = 0) -> dict:
        if top not in TOP_SIZES:
            raise ApiError(400, f"top must be one of {TOP_SIZES}")
        snap = self.snapshot(snapshot_id)
        rows = self.conn.execute(
            "SELECT * FROM snapshot_wallets WHERE snapshot_id = ? ORDER BY rank LIMIT ? OFFSET ?", (snap["snapshotId"], top, offset)
        ).fetchall()
        return {"snapshot": self.meta(snap), "top": top, "offset": offset, "ordering": "score desc, then numeric wallet address asc", "rows": [wallet_json(r) for r in rows]}

    def ranking(self, kind: str, limit: int, snapshot_id: str | None) -> dict:
        if kind not in RANKINGS:
            raise ApiError(404, f"unknown ranking; choose one of {sorted(RANKINGS)}")
        order = RANKINGS[kind][0]
        where = RANKINGS[kind][2] if len(RANKINGS[kind]) > 2 else "1 = 1"
        snap = self.snapshot(snapshot_id)
        rows = self.conn.execute(
            f"SELECT * FROM snapshot_wallets WHERE snapshot_id = ? AND {where} ORDER BY {order} LIMIT ?", (snap["snapshotId"], max(1, min(limit, 1000)))
        ).fetchall()
        return {"snapshot": self.meta(snap), "ranking": kind, "definition": RANKINGS[kind][1], "dataQuality": snap["metadata"]["dataQuality"], "rows": [wallet_json(r) for r in rows]}

    def targets(self, q: dict, snapshot_id: str | None) -> dict:
        snap = self.snapshot(snapshot_id)
        clauses, params = ["snapshot_id = ?"], [snap["snapshotId"]]
        applied = {}

        def flag(name: str) -> bool:
            v = q.get(name, [""])[0].lower()
            return v in ("1", "true", "yes")

        def number(name: str):
            v = q.get(name, [""])[0]
            if v == "":
                return None
            try:
                return float(v) if "." in v else int(v)
            except ValueError:
                raise ApiError(400, f"{name} must be a number") from None

        if flag("activatedOnly"):
            clauses.append("seat_status = 'activated'"); applied["activatedOnly"] = True
        if (v := number("minScore")) is not None:
            clauses.append("score >= ?"); params.append(int(v)); applied["minScore"] = int(v)
        tier = q.get("tier", [""])[0]
        if tier:
            idx = TIERS.index(tier) if tier in TIERS else (int(tier) if tier.isdigit() and int(tier) < 4 else None)
            if idx is None:
                raise ApiError(400, f"tier must be one of {TIERS} or 0-3")
            clauses.append("tier = ?"); params.append(idx); applied["tier"] = TIERS[idx]
        if (v := number("minHoldSeconds")) is not None:
            clauses.append("current_hold_seconds >= ?"); params.append(int(v)); applied["minHoldSeconds"] = int(v)
        if (v := number("minHoldDays")) is not None:
            clauses.append("current_hold_seconds >= ?"); params.append(int(v * 86400)); applied["minHoldDays"] = v
        if (v := number("minBalance")) is not None:  # whole IMD
            raw = int(round(v * 10**18))
            clauses.append("CAST(balance AS REAL) >= ? AND (LENGTH(balance) > ? OR (LENGTH(balance) = ? AND balance >= ?))")
            params.extend([float(raw), len(str(raw)), len(str(raw)), str(raw)]); applied["minBalance"] = v
        if (v := number("minRetentionRatio")) is not None:
            clauses.append("retention_ratio_bps >= ?"); params.append(int(round(float(v) * 10000))); applied["minRetentionRatio"] = v
        if flag("neverSent"):
            clauses.append("never_sent_after_first = 1"); applied["neverSent"] = True
        if flag("retainedAll"):
            clauses.append("retained_all = 1"); applied["retainedAll"] = True
        if flag("heldContinuously"):
            clauses.append("held_continuously = 1"); applied["heldContinuously"] = True
        limit = number("limit") or 100
        limit = max(1, min(int(limit), 1000))
        rows = self.conn.execute(
            f"SELECT * FROM snapshot_wallets WHERE {' AND '.join(clauses)} ORDER BY rank LIMIT ?", (*params, limit)
        ).fetchall()
        total = self.conn.execute(f"SELECT COUNT(*) AS n FROM snapshot_wallets WHERE {' AND '.join(clauses)}", params).fetchone()["n"]
        return {"snapshot": self.meta(snap), "filters": applied, "limit": limit, "matched": total, "dataQuality": snap["metadata"]["dataQuality"], "rows": [wallet_json(r) for r in rows]}

    def publication(self, snapshot_id: str | None) -> dict:
        snap = self.snapshot(snapshot_id)
        path = self.cfg.publication_dir / f"{snap['snapshotId']}.json"
        if not path.exists():
            raise ApiError(404, "no publication payload stored for this snapshot")
        return json.loads(path.read_text())

    def site_feed(self, snapshot_id: str | None) -> dict:
        """Compact feed in the shape the static website consumes."""
        snap = self.snapshot(snapshot_id)
        q = snap["metadata"]["dataQuality"]
        return {
            "source": "service",
            "snapshotId": snap["snapshotId"],
            "epoch": str(snap["sequence"]),
            "block": str(snap["asOfBlock"]),
            "timestamp": snap["asOfTimestamp"],
            "publishedAt": snap["createdAt"],
            "totalSeats": str(snap["totalSeats"] or 0),
            "activatedSeats": str(snap["activatedSeats"] or 0),
            "wallets": snap["rankedWallets"],
            "stale": not q.get("transferHistoryComplete", False),
            "currentConfiguration": True,
            "evidenceHash": "0x" + snap["contentHash"],
            "scoreVersion": snap["scoreVersion"],
            "dataQuality": q,
        }

    # Routing -------------------------------------------------------------

    def handle(self, path: str, query: dict) -> dict:
        sid = query.get("snapshot", [None])[0]
        parts = [p for p in path.split("/") if p]
        if parts[:1] != ["v1"]:
            raise ApiError(404, "unknown route; see /v1")
        rest = parts[1:]
        if not rest:
            return {
                "routes": [
                    "/v1/health", "/v1/status", "/v1/snapshots", "/v1/snapshot/latest", "/v1/snapshot/<id>",
                    "/v1/wallets?addresses=0x..,0x..", "/v1/leaderboard?top=10|50|100|1000",
                    "/v1/rankings/<current-holding|longest-holding|balance|retained-all|retention-ratio|never-sent>?limit=N",
                    "/v1/targets?activatedOnly=1&minScore=..&tier=..&minHoldDays=..&minBalance=..&minRetentionRatio=..&neverSent=1&heldContinuously=1&retainedAll=1&limit=N",
                    "/v1/publication/latest", "/v1/site-feed",
                ],
                "note": "add ?snapshot=<id> to any query to read a prior immutable snapshot",
            }
        if rest == ["health"]:
            return {"ok": True, "now": int(time.time())}
        if rest == ["status"]:
            return self.status()
        if rest == ["snapshots"]:
            return self.snapshots()
        if rest[0] == "snapshot" and len(rest) == 2:
            return self.snapshot(rest[1])
        if rest == ["wallets"]:
            raw = ",".join(query.get("addresses", []) + query.get("address", []))
            return self.wallets([a for a in re.split(r"[\s,]+", raw) if a], sid)
        if rest == ["leaderboard"]:
            return self.leaderboard(int(query.get("top", ["10"])[0]), sid, int(query.get("offset", ["0"])[0]))
        if rest[0] == "rankings" and len(rest) == 2:
            return self.ranking(rest[1], int(query.get("limit", ["100"])[0]), sid)
        if rest == ["targets"]:
            return self.targets(query, sid)
        if rest[0] == "publication" and len(rest) == 2:
            return self.publication(rest[1])
        if rest == ["site-feed"]:
            return self.site_feed(sid)
        raise ApiError(404, "unknown route; see /v1")


def make_server(conn: sqlite3.Connection, cfg: Config) -> ThreadingHTTPServer:
    api = Api(conn, cfg)

    class Handler(BaseHTTPRequestHandler):
        server_version = "chadboard-data/1.0"

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.send_header("access-control-allow-origin", "*")
            self.send_header("cache-control", "public, max-age=60")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, HEAD, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            try:
                self._send(200, api.handle(url.path, parse_qs(url.query)))
            except ApiError as err:
                self._send(err.status, {"error": str(err)})
            except ValueError as err:
                self._send(400, {"error": str(err)[:200]})
            except Exception as err:  # noqa: BLE001
                self._send(500, {"error": "internal error", "detail": str(err)[:200]})

        def do_POST(self) -> None:  # noqa: N802
            self._send(405, {"error": "read-only API: GET only"})

        do_PUT = do_DELETE = do_PATCH = do_POST

        def log_message(self, fmt: str, *args) -> None:
            return

    return ThreadingHTTPServer((cfg.host, cfg.port), Handler)
