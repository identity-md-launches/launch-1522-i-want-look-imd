"""Optional, non-authoritative IMD Radar observations. No ranking code imports this module.

Only the three structured endpoints are accepted. Exact response bytes are retained
before validation. A malformed/outage response never replaces the last good cache.
The upstream has no schema version; SCHEMA identifies this explicit decoder.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

from . import db
from .config import Config

SWARM = "https://www.imdradar.site/api/feed?view=swarm"
AGENTS = "https://www.imdradar.site/api/launchpad?view=agents"
SEAT = "https://www.imdradar.site/api/feed?view=seat&id="
SCHEMA = "imd-radar-observed-2026-10/v1"
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
MAX_BYTES = 12 * 1024 * 1024


class SchemaError(ValueError):
    pass


def integer(v, label="integer"):
    if type(v) is not int or v < 0 or v > 2**53 - 1:
        raise SchemaError(f"invalid {label}")
    return v


def number(v):
    if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
        raise SchemaError("invalid nonnegative number")
    return Decimal(str(v))


def wallet(v):
    if not isinstance(v, str) or not ADDRESS.fullmatch(v) or int(v, 16) == 0:
        raise SchemaError("invalid wallet")
    return v.lower()


def timestamp(v):
    if not isinstance(v, str):
        raise SchemaError("missing source timestamp")
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError()
        return int(t.timestamp())
    except (ValueError, OverflowError):
        raise SchemaError("invalid source timestamp") from None


def array(v, limit=10000):
    if not isinstance(v, list) or len(v) > limit:
        raise SchemaError("invalid collection")
    return v


def normalize(url: str, body: dict, cfg: Config) -> dict:
    if not isinstance(body, dict):
        raise SchemaError("expected an object")
    if url == SWARM:
        seats = []
        for r in array(body.get("seats")):
            if not isinstance(r, list) or len(r) != 11:
                raise SchemaError("expected an 11-field swarm seat tuple")
            for v in r[:10]:
                integer(v)
            seats.append({"seat": r[0], "agentId": r[1], "owner": wallet(r[10]),
                          "attempts": r[2], "accepted": r[3], "rejected": r[4],
                          "failed": r[5], "pending": r[6], "latestWorkAt": r[7] // 1000 or None,
                          # Undocumented compact flags are retained, never guessed as activation/online.
                          "compactFlags": r[8:10], "online": None, "status": None})
        events = array(body.get("events", []))
        running = array(body.get("running", []))
        if any(not isinstance(e, dict) for e in events + running):
            raise SchemaError("invalid activity record")
        return {"kind": "swarm", "sourceUpdatedAt": timestamp(body.get("at")), "seats": seats,
                "events": events, "running": running, "health": body.get("health"), "counts": body.get("counts")}
    if url.startswith(SEAT) and url[len(SEAT):].isdigit():
        seat = integer(body.get("seat"), "seat")
        if seat != int(url[len(SEAT):]):
            raise SchemaError("seat response does not match request")
        if type(body.get("online")) is not bool or not isinstance(body.get("status"), str):
            raise SchemaError("invalid seat online/status")
        work = array(body.get("work"))
        times = []
        for entry in work:
            if not isinstance(entry, dict):
                raise SchemaError("invalid work record")
            times.append(timestamp(entry.get("at")))
        item = {"seat": seat, "agentId": integer(body.get("agentId")), "owner": wallet(body.get("owner")),
                "online": body["online"], "status": body["status"][:80], "latestWorkAt": max(times, default=None),
                "work": work}
        for field in ("attempts", "accepted", "rejected", "failed", "pending"):
            item[field] = integer(body.get(field), field)
        # This endpoint has no observation timestamp. Retrieval time is not latest-work time.
        return {"kind": "seat", "sourceUpdatedAt": None, "seats": [item]}
    if url == AGENTS:
        minimum = max(Decimal(cfg.radar_min_liquidity_usd), number(body.get("minLiquidityUsd")))
        launches = {}
        for launch in array(body.get("launches")):
            if not isinstance(launch, dict):
                raise SchemaError("invalid launch")
            n = integer(launch.get("n"))
            if n in launches:
                raise SchemaError("duplicate launch definition")
            if type(launch.get("counted")) is not bool:
                raise SchemaError("invalid liquidity eligibility flag")
            liquidity, price = number(launch.get("liquidityUsd")), number(launch.get("priceUsd"))
            launches[n] = {"launch": n, "symbol": str(launch.get("symbol", ""))[:64],
                           "liquidityUsd": format(liquidity, "f"), "priceUsd": format(price, "f"),
                           "eligible": launch["counted"] and liquidity >= minimum and price > 0}
        agents = []
        for agent in array(body.get("agents")):
            if not isinstance(agent, dict):
                raise SchemaError("invalid launch agent")
            rewards, excluded, participation = [], [], []
            seen = set()
            value = unclaimed = Decimal(0)
            for token in array(agent.get("tokens")):
                if not isinstance(token, list) or len(token) != 3:
                    raise SchemaError("expected a 3-field launch reward tuple")
                launch_id, amount, claimed = integer(token[0]), number(token[1]), integer(token[2])
                if claimed not in (0, 1) or launch_id in seen:
                    raise SchemaError("invalid or duplicate launch reward")
                seen.add(launch_id)
                participation.append(launch_id)
                launch = launches.get(launch_id)
                if launch is None or not launch["eligible"]:
                    excluded.append({"launch": launch_id, "reason": "low-or-unverified-liquidity"})
                    continue
                usd = amount * Decimal(launch["priceUsd"])
                value += usd
                if not claimed:
                    unclaimed += usd
                rewards.append({**launch, "rewardTokens": format(amount, "f"), "claimed": bool(claimed),
                                "unclaimedTokens": "0" if claimed else format(amount, "f"), "valueUsd": format(usd, "f")})
            agents.append({"wallet": wallet(agent.get("wallet")),
                           "seats": [integer(s) for s in array(agent.get("seats"))],
                           "acceptedTasks": integer(agent.get("acceptedTasks")),
                           "launchesReported": integer(agent.get("launches")), "participation": participation,
                           "reportedValueUsd": format(number(agent.get("valueUsd")), "f"),
                           "reportedUnclaimedUsd": format(number(agent.get("unclaimedUsd")), "f"),
                           "eligibleValueUsd": format(value, "f"), "eligibleUnclaimedUsd": format(unclaimed, "f"),
                           "rewards": rewards, "excluded": excluded})
        return {"kind": "agents", "sourceUpdatedAt": timestamp(body.get("updatedAt")),
                "minLiquidityUsd": str(minimum), "agents": agents}
    raise SchemaError("endpoint not allowed")


def fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "chadboard-radar/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise SchemaError("unexpected Radar redirect")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SchemaError("Radar response exceeds size limit")
        return data


class Radar:
    def __init__(self, conn, cfg: Config, transport=fetch, clock=time.time):
        self.conn, self.cfg, self.transport, self.clock = conn, cfg, transport, clock

    def ingest(self, url, raw: bytes, retrieved_at: int) -> int | None:
        normalized, error = None, None
        try:
            if len(raw) > MAX_BYTES:
                raise SchemaError("Radar response exceeds size limit")
            normalized = normalize(url, json.loads(raw), self.cfg)
        except (ValueError, TypeError, KeyError, OverflowError):
            error = "malformed-response"  # Untrusted body text never becomes an error message.
        cur = self.conn.execute(
            "INSERT INTO radar_responses(source_url,retrieved_at,response_hash,schema_version,raw_body,valid,normalized,error) VALUES(?,?,?,?,?,?,?,?)",
            (url, retrieved_at, hashlib.sha256(raw).hexdigest(), SCHEMA, raw, int(normalized is not None),
             json.dumps(normalized) if normalized is not None else None, error))
        response_id = cur.lastrowid if normalized is not None else None
        self._attempt(url, retrieved_at, error, response_id)
        return response_id

    def _attempt(self, url, at, error, response_id=None):
        self.conn.execute(
            "INSERT INTO radar_cache(source_url,response_id,attempted_at,error) VALUES(?,?,?,?) "
            "ON CONFLICT(source_url) DO UPDATE SET response_id=COALESCE(excluded.response_id,radar_cache.response_id),attempted_at=excluded.attempted_at,error=excluded.error",
            (url, response_id, at, error))

    def refresh(self, force=False) -> dict:
        if not self.cfg.radar_enabled:
            return self.status()
        deadline = time.monotonic() + max(1, self.cfg.radar_budget_seconds)

        def acquire(url):
            try:
                return url, self.transport(url, self.cfg.radar_timeout), None, int(self.clock())
            except Exception:
                return url, None, "unavailable", int(self.clock())

        def batch(urls):
            now = int(self.clock())
            due = []
            for url in urls:
                cached = self.conn.execute("SELECT * FROM radar_cache WHERE source_url=?", (url,)).fetchone()
                # Also back off after failures; API reads never trigger requests.
                if force or not cached or now - cached["attempted_at"] >= self.cfg.radar_ttl:
                    due.append(url)
            with ThreadPoolExecutor(max_workers=4) as pool:
                completed, failed = [], 0
                for i in range(0, len(due), 4):
                    if time.monotonic() >= deadline or failed >= 4:
                        break
                    for url, raw, error, at in pool.map(acquire, due[i:i+4]):
                        completed.append(url)
                        if error:
                            failed += 1
                            self._attempt(url, at, error)
                        else:
                            failed = 0
                            self.ingest(url, raw, at)
                return completed

        batch([SWARM, AGENTS])
        swarm = next((r for r in self.responses() if r["source_url"] == SWARM), None)
        swarm_attempt = self.conn.execute("SELECT error FROM radar_cache WHERE source_url=?", (SWARM,)).fetchone()
        if swarm and swarm_attempt and not swarm_attempt["error"]:
            ids = sorted({s["seat"] for s in json.loads(swarm["normalized"])["seats"]})
            # Rotation allows an explicitly bounded worker to eventually cover every seat.
            offset = int(db.get_setting(self.conn, "radar.seatOffset", "0")) % max(len(ids), 1)
            ordered = ids[offset:] + ids[:offset]
            chosen = ordered[:max(0, self.cfg.radar_seat_limit)]
            done = batch([SEAT + str(seat) for seat in chosen])
            # Move only past completed work when a deadline/circuit breaker stops us.
            advanced = len(chosen) if len(done) == len(chosen) else len(done)
            db.set_setting(self.conn, "radar.seatOffset", str(offset + advanced))
        return self.status()

    def responses(self, snapshot_id=None):
        if snapshot_id:
            return self.conn.execute("SELECT r.* FROM radar_responses r JOIN snapshot_radar s ON r.id=s.response_id WHERE s.snapshot_id=? ORDER BY r.id", (snapshot_id,)).fetchall()
        return self.conn.execute("SELECT r.* FROM radar_responses r JOIN radar_cache c ON r.id=c.response_id ORDER BY r.id").fetchall()

    def bind(self, snapshot_id):
        # Called once for a newly created snapshot. Never rebind an existing observation set.
        if db.get_setting(self.conn, "radar.bound." + snapshot_id):
            return
        self.conn.execute("BEGIN")
        try:
            self.conn.executemany("INSERT OR IGNORE INTO snapshot_radar VALUES(?,?)", [(snapshot_id, r["id"]) for r in self.responses()] if self.cfg.radar_enabled else [])
            db.set_setting(self.conn, "radar.bound." + snapshot_id, "1")
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def provenance(self, r):
        n = json.loads(r["normalized"])
        now = int(self.clock())
        observed = n.get("sourceUpdatedAt")
        future = observed is not None and observed > now + 300
        stale = now - min(r["retrieved_at"], observed if observed is not None else r["retrieved_at"]) > self.cfg.radar_max_age
        return {"source": "imd-radar", "sourceRetrievedAt": r["retrieved_at"], "sourceUpdatedAt": observed,
                "asOfBlock": None, "sourceUrl": r["source_url"], "responseId": r["id"],
                "responseHash": r["response_hash"], "schemaVersion": r["schema_version"],
                "dataQuality": {"stale": stale, "futureTimestamp": future, "unverified": True,
                                "sourceTimestampAvailable": observed is not None}}

    def status(self):
        rows = self.responses()
        sources = [self.provenance(r) for r in rows]
        failures = [dict(r) for r in self.conn.execute("SELECT source_url AS sourceUrl,attempted_at AS attemptedAt,error FROM radar_cache WHERE error IS NOT NULL")]
        return {"source": "imd-radar", "sourceRetrievedAt": max((s["sourceRetrievedAt"] for s in sources), default=None),
                "asOfBlock": None, "enabled": self.cfg.radar_enabled, "cachedResponses": len(rows),
                "dataQuality": {"status": "disabled" if not self.cfg.radar_enabled else "unavailable" if not rows else "degraded" if failures else "cached",
                                "staleResponses": sum(s["dataQuality"]["stale"] for s in sources), "unverified": True},
                "seatDetailsCached": sum(r["source_url"].startswith(SEAT) for r in rows),
                "seatLimitPerRefresh": self.cfg.radar_seat_limit,
                "failures": failures, "conflict": False, "conflicts": [], "rankingAuthority": "ethereum"}

    def observations(self, snapshot_id=None, address=None, seat=None, ethereum_snapshot_id=None):
        seats, agents, sources = [], [], []
        for r in self.responses(snapshot_id):
            n, p = json.loads(r["normalized"]), self.provenance(r)
            sources.append(p)
            for s in n.get("seats", []):
                seats.append({**s, **p})
            for a in n.get("agents", []):
                agents.append({**a, **p})
        # Keep distinct observations of a relationship (swarm, details, launch rewards).
        # Repeated same-source entries are deduplicated with an explicit diagnostic.
        relationships, seen, conflicts, owners = [], set(), [], {}
        for record in seats + [{**a, "seat": s, "owner": a["wallet"]} for a in agents for s in a["seats"]]:
            key = (record["seat"], record["owner"], record["responseId"])
            if key in seen:
                conflicts.append({"field": "relationship", "kind": "duplicate-relationship", "seat": record["seat"], "wallet": record["owner"], "responseId": record["responseId"]})
                continue
            seen.add(key)
            owners.setdefault(record["seat"], set()).add(record["owner"])
            relationships.append({k: record[k] for k in ("seat", "owner", "source", "sourceRetrievedAt", "responseId", "dataQuality")})
        for seat_id, wallets in owners.items():
            if len(wallets) > 1:
                conflicts.append({"field": "owner", "kind": "radar-disagreement", "seat": seat_id, "radar": sorted(wallets), "preferredSource": "ethereum"})
        chain = []
        ethereum_snapshot_id = ethereum_snapshot_id or snapshot_id
        chain_snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=?", (ethereum_snapshot_id,)).fetchone() if ethereum_snapshot_id else None
        if chain_snapshot:
            chain = [{**dict(r), "source": "ethereum", "asOfBlock": chain_snapshot["as_of_block"], "sourceRetrievedAt": chain_snapshot["created_at"]} for r in self.conn.execute("SELECT seat_id AS seat,wallet,active FROM snapshot_seats WHERE snapshot_id=?", (ethereum_snapshot_id,))]
            for e in chain:
                rs = owners.get(int(e["seat"]), set())
                if any(w != e["wallet"] for w in rs):
                    conflicts.append({"field": "owner", "kind": "ethereum-radar-disagreement", "seat": int(e["seat"]), "ethereum": e["wallet"], "radar": sorted(rs), "preferredSource": "ethereum", "note": "Radar observation time may differ from the snapshot block."})
                for s in seats:
                    if s["seat"] == int(e["seat"]) and e["active"] is not None and s.get("status") in ("active", "inactive", "disabled") and bool(e["active"]) != (s["status"] == "active"):
                        conflicts.append({"field": "activeSeat", "kind": "status-disagreement", "seat": s["seat"], "ethereum": bool(e["active"]), "radar": s["status"], "preferredSource": "ethereum", "note": "Radar agent status and Ethereum activation describe different evidence."})
        result = {"source": "merged" if chain else "imd-radar", "sourceRetrievedAt": max((s["sourceRetrievedAt"] for s in sources), default=None),
                  "asOfBlock": None, "seats": seats, "relationships": relationships, "launches": agents,
                  "ethereumAsOfBlock": chain_snapshot["as_of_block"] if chain_snapshot else None,
                  "ethereumRelationships": chain, "sources": sources, "conflict": bool(conflicts), "conflicts": conflicts,
                  "dataQuality": {"unverified": True, "stale": any(s["dataQuality"]["stale"] for s in sources),
                                  "available": bool(sources), "rankingEligible": False},
                  "note": "Supplementary observations only. Ethereum at the snapshot block determines ranks, IMD balances and transfer accounting. Reward estimates are not proof of sales or retention."}
        return select_observations(result, address, seat)

    def activity(self):
        for r in self.responses():
            n = json.loads(r["normalized"])
            if n["kind"] == "swarm":
                return {**self.provenance(r), "events": n["events"], "running": n["running"], "counts": n["counts"], "health": n["health"], "conflict": False, "conflicts": []}
        return {**self.status(), "events": [], "running": []}


def select_observations(bundle, address=None, seat=None):
    """Filter an already-decoded bundle; one decode for an entire leaderboard request."""
    result = dict(bundle)
    if address is not None or seat is not None:
        relevant = {int(e["seat"]) for e in bundle["ethereumRelationships"] if address and e["wallet"] == address}
        relevant.update(r["seat"] for r in bundle["relationships"] if address and r["owner"] == address)
        if seat is not None:
            relevant = {seat}
        for key in ("seats", "relationships", "conflicts"):
            result[key] = [r for r in bundle[key] if r.get("seat") in relevant]
        result["ethereumRelationships"] = [r for r in bundle["ethereumRelationships"] if int(r["seat"]) in relevant]
        result["launches"] = [a for a in bundle["launches"] if (address and a["wallet"] == address) or (seat is not None and seat in a["seats"])]
        ids = {s["responseId"] for s in result["seats"] + result["launches"] + result["relationships"]}
        result["sources"] = [s for s in bundle["sources"] if s["responseId"] in ids]
    result["sourceRetrievedAt"] = max((s["sourceRetrievedAt"] for s in result["sources"]), default=None)
    result["conflict"] = bool(result["conflicts"])
    detailed = {s["seat"] for s in result["seats"] if s.get("status") is not None}
    result["dataQuality"] = {**bundle["dataQuality"], "available": bool(result["sources"]),
                             "stale": any(s["dataQuality"]["stale"] for s in result["sources"]),
                             "seatDetailsComplete": all(r["seat"] in detailed for r in result["relationships"])}
    return result
