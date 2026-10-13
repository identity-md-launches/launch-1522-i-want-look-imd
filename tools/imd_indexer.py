#!/usr/bin/env python3
"""Finalized-log IMD analytics. Standard library only. Never signs or broadcasts.

See docs/INDEXER.md for the required policy and supported event semantics.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "00" * 20  # Actual mint/burn sentinel in Transfer events, never a deployment default.
WINDOW = 30 * 86400
METRICS = ("active_seats", "launches", "eligible_claims", "claimed_claims", "total_claim_delay",
           "max_claim_delay", "interactions", "distinct_apps")
AMOUNTS = ("claimed", "bought", "sold", "other_out", "reward_held", "reward_sold", "reward_other_out", "balance")
METRIC_ABI = "(uint32,uint32,uint32,uint32,uint64,uint64,uint32,uint16)"
TOKEN_ABI = "(" + ",".join(["uint128"] * 8) + ")"
ROW_ABI = f"(address,{METRIC_ABI},{TOKEN_ABI}[])"
BEGIN_ABI = "beginEpoch((uint64,uint64,bytes32,uint64,uint64,uint32,bytes32,uint64))"
REQUIRED_FIELDS = {
    "activate": {"seat"}, "deactivate": {"seat"}, "launch": {"wallet", "id"},
    "eligible": {"wallet", "allocation", "token", "amount"},
    "claim": {"wallet", "allocation", "token", "amount", "counterparty"},
    "buy": {"wallet", "token", "amount", "counterparty"},
    "sell": {"wallet", "token", "amount", "counterparty"}, "interact": {"wallet"},
}


class AuditError(ValueError):
    """Incomplete, inconsistent or unsupported observations: refuse to publish."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def uint(value, bits=256):
    require(not isinstance(value, bool) and isinstance(value, (int, str)), "expected unsigned integer")
    try:
        result = int(value, 16 if value.startswith("0x") else 10) if isinstance(value, str) else value
    except ValueError as exc:
        raise AuditError("invalid unsigned integer") from exc
    require(0 <= result < 2**bits, f"integer exceeds uint{bits}")
    return result


def address(value, allow_zero=False):
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value), "invalid address")
    result = value.lower()
    require(allow_zero or result != ZERO, "zero address is not configured")
    return result


def hash32(value):
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value), "invalid bytes32")
    require(int(value, 16) != 0, "zero hash")
    return value.lower()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(value):
    return "0x" + hashlib.sha256(canonical(value)).hexdigest()


def word(value):
    return f"{uint(value):064x}"


def locator_valid(location):
    if isinstance(location, dict):
        require(set(location) == {"constant"}, "invalid constant locator")
        uint(location["constant"])
    else:
        require(isinstance(location, str) and re.fullmatch(r"(topic|data):[0-9]+", location), "invalid locator")
        kind, index = location.split(":")
        require(1 <= int(index) <= 3 if kind == "topic" else int(index) < 128, "locator out of bounds")


def read_word(log, location):
    if isinstance(location, dict):
        return uint(location["constant"])
    kind, index = location.split(":")
    index = int(index)
    if kind == "topic":
        require(index < len(log["topics"]), "missing indexed event field")
        return uint(log["topics"][index])
    data = log["data"][2:]
    require(len(data) % 64 == 0 and (index + 1) * 64 <= len(data), "missing ABI event word")
    return uint("0x" + data[index * 64:(index + 1) * 64])


class Policy:
    def __init__(self, raw):
        required = {"version", "chain_id", "start_block", "seat_nft", "seat_wallet_mode",
                    "activation_survives_transfer", "tokens", "events"}
        require(isinstance(raw, dict) and set(raw) == required, "policy keys differ from documented schema")
        require(raw["version"] == 1 and raw["chain_id"] == 1, "policy must target Ethereum, version 1")
        self.raw = raw
        self.hash = digest(raw)
        self.start = uint(raw["start_block"], 64)
        self.nft = address(raw["seat_nft"])
        require(raw["seat_wallet_mode"] in ("owner", "activation"), "unknown seat wallet semantics")
        require(isinstance(raw["activation_survives_transfer"], bool), "specify transfer activation semantics")
        require(isinstance(raw["tokens"], list) and 1 <= len(raw["tokens"]) <= 16, "configure 1..16 tokens")
        self.tokens = []
        for token in raw["tokens"]:
            require(set(token) == {"address", "support_target"}, "invalid token policy")
            item = {"address": address(token["address"]), "support_target": uint(token["support_target"], 128)}
            require(item["support_target"] > 0 and item["address"] != self.nft, "invalid support target/token")
            self.tokens.append(item)
        require([t["address"] for t in self.tokens] == sorted({t["address"] for t in self.tokens}),
                "token policies must be unique and sorted by numeric address")
        self.schemas = defaultdict(list)
        kinds = set()
        require(isinstance(raw["events"], list), "events must be an array")
        for event in raw["events"]:
            require({"kind", "address", "topic0", "fields"} <= set(event)
                    and set(event) <= {"kind", "address", "topic0", "fields", "group", "app", "where"},
                    "invalid event descriptor")
            kind = event["kind"]
            require(kind in REQUIRED_FIELDS, "unknown event kind")
            fields = set(REQUIRED_FIELDS[kind])
            if kind == "activate" and raw["seat_wallet_mode"] == "activation":
                fields.add("wallet")
            require(set(event["fields"]) == fields, f"wrong fields for {kind}")
            for location in event["fields"].values():
                locator_valid(location)
            for condition in event.get("where", []):
                require(set(condition) == {"field", "op", "value"} and condition["op"] in ("eq", "gt"),
                        "invalid event condition")
                locator_valid(condition["field"])
                uint(condition["value"])
            if kind in ("launch", "eligible", "claim"):
                require(isinstance(event.get("group"), str) and bool(event["group"]), "event ID namespace required")
            if kind == "interact":
                require(isinstance(event.get("app"), str) and bool(event["app"]), "app identity required")
            emitter, topic = address(event["address"]), hash32(event["topic0"])
            require(topic != TRANSFER, "Transfer events are decoded automatically")
            self.schemas[(emitter, topic)].append(event)
            kinds.add(kind)
        require({"activate", "launch", "eligible", "claim", "buy", "sell", "interact"} <= kinds,
                "all five analytics dimensions and seat activation need configured event sources")

    def decode(self, log):
        matches = []
        for schema in self.schemas.get((log["address"].lower(), log["topics"][0].lower()), []):
            if not all((read_word(log, c["field"]) == uint(c["value"]) if c["op"] == "eq"
                        else read_word(log, c["field"]) > uint(c["value"])) for c in schema.get("where", [])):
                continue
            item = {"kind": schema["kind"], "group": schema.get("group"), "app": schema.get("app")}
            for name, location in schema["fields"].items():
                value = read_word(log, location)
                if name in ("wallet", "token", "counterparty"):
                    require(value < 2**160, "non-canonical ABI address")
                    value = address("0x" + f"{value:040x}", allow_zero=(name == "counterparty"))
                item[name] = value
            matches.append(item)
        require(len(matches) <= 1, "ambiguous event schema; make where conditions mutually exclusive")
        return matches[0] if matches else None


class Rpc:
    def __init__(self, url):
        require(url.startswith(("http://", "https://")), "RPC must be an HTTP(S) URL")
        self.url = url
        self.counter = 0

    def call(self, method, params):
        # A hard allowlist prevents this utility from ever sending a transaction.
        require(method in {"eth_chainId", "eth_getBlockByNumber", "eth_getLogs", "eth_call", "eth_getCode"},
                "non-read-only RPC forbidden")
        self.counter += 1
        request = urllib.request.Request(self.url, data=canonical({"jsonrpc": "2.0", "id": self.counter,
                                        "method": method, "params": params}),
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            # Do not echo a credential-bearing RPC URL.
            raise AuditError(f"RPC transport failed during {method}: {type(exc).__name__}") from None
        require(isinstance(body, dict) and body.get("id") == self.counter and "error" not in body
                and "result" in body, f"RPC rejected or malformed {method}")
        return body["result"]


def transfer(log, nft=False):
    expected = 4 if nft else 3
    require(len(log["topics"]) == expected, "unsupported Transfer event shape")
    origin = read_word(log, "topic:1")
    destination = read_word(log, "topic:2")
    require(origin < 2**160 and destination < 2**160, "non-canonical Transfer address")
    return ("0x" + f"{origin:040x}", "0x" + f"{destination:040x}",
            read_word(log, "topic:3" if nft else "data:0"))


def metric_defaults():
    return {key: 0 for key in METRICS}


def amount_defaults():
    return {key: 0 for key in AMOUNTS}


class Ledger:
    def __init__(self, policy):
        self.policy = policy
        self.owners = {}
        self.activated = {}
        self.active_seats = Counter()
        self.metrics = defaultdict(metric_defaults)
        self.portfolios = defaultdict(amount_defaults)
        self.launches = set()
        self.allocations = {}
        self.apps = defaultdict(set)
        self.interactions = set()
        self.token_addresses = {t["address"] for t in policy.tokens}

    def observe_seats(self, logs):
        for log in logs:
            if log["address"].lower() == self.policy.nft and log["topics"][0].lower() == TRANSFER:
                origin, destination, seat = transfer(log, nft=True)
                require(destination != ZERO or origin != ZERO, "invalid NFT mint/burn")
                if origin == ZERO:
                    require(seat not in self.owners, "duplicate NFT mint")
                else:
                    require(self.owners.get(seat) == origin, "incomplete or inconsistent NFT transfer history")
                if destination == ZERO:
                    self.owners.pop(seat)
                    self.activated.pop(seat, None)
                else:
                    self.owners[seat] = destination
                    if origin != ZERO and origin != destination and not self.policy.raw["activation_survives_transfer"]:
                        self.activated.pop(seat, None)
            else:
                event = self.policy.decode(log)
                if event and event["kind"] in ("activate", "deactivate"):
                    seat = event["seat"]
                    require(seat in self.owners, "activation event for nonexistent NFT")
                    if event["kind"] == "activate":
                        self.activated[seat] = event.get("wallet", self.owners[seat])
                    else:
                        self.activated.pop(seat, None)

    def finish_census(self):
        self.active_seats = Counter(self.owners[seat] if self.policy.raw["seat_wallet_mode"] == "owner" else wallet
                                    for seat, wallet in self.activated.items())
        for wallet, count in self.active_seats.items():
            self.metrics[wallet]["active_seats"] = count

    def observe_activity(self, logs, timestamp):
        decoded = [(log, self.policy.decode(log)) for log in logs]
        transfers = [(log, transfer(log)) for log in logs
                     if log["address"].lower() in self.token_addresses and log["topics"][0].lower() == TRANSFER]
        classifications = {}
        # Match the entire transaction before processing log order: a claim event usually follows its Transfer.
        for log, event in decoded:
            if not event or event["kind"] not in ("claim", "buy", "sell") or event["wallet"] not in self.active_seats:
                continue
            token, wallet, counterparty = event["token"], event["wallet"], event["counterparty"]
            require(token in self.token_addresses and event["amount"] > 0, "unsupported token or zero activity amount")
            require(wallet != counterparty and (counterparty != ZERO or event["kind"] == "claim"),
                    "self trade or zero venue")
            origin, destination = (wallet, counterparty) if event["kind"] == "sell" else (counterparty, wallet)
            candidates = [item for item, movement in transfers if item["address"].lower() == token
                          and movement == (origin, destination, event["amount"])
                          and uint(item["logIndex"]) not in classifications]
            require(bool(candidates), "activity event lacks a matching, unused token Transfer")
            require(len(candidates) == 1, "ambiguous activity Transfer; an ABI-specific adapter must resolve it")
            classifications[uint(candidates[0]["logIndex"])] = event["kind"]

        for log, event in decoded:
            token = log["address"].lower()
            if token in self.token_addresses and log["topics"][0].lower() == TRANSFER:
                origin, destination, amount = transfer(log)
                if origin == destination or amount == 0:
                    continue
                classification = classifications.get(uint(log["logIndex"]))
                if origin in self.active_seats:
                    portfolio = self.portfolios[(origin, token)]
                    disposed = min(amount, portfolio["reward_held"])
                    portfolio["reward_held"] -= disposed
                    is_sale = classification == "sell"
                    portfolio["sold" if is_sale else "other_out"] += amount
                    portfolio["reward_sold" if is_sale else "reward_other_out"] += disposed
                if destination in self.active_seats:
                    portfolio = self.portfolios[(destination, token)]
                    if classification == "claim":
                        portfolio["claimed"] += amount
                        portfolio["reward_held"] += amount
                    elif classification == "buy":
                        portfolio["bought"] += amount
            if not event or event.get("wallet") not in self.active_seats:
                continue
            wallet, kind = event["wallet"], event["kind"]
            metrics = self.metrics[wallet]
            if kind == "launch":
                key = (event["group"], event["id"])
                require(key not in self.launches, "duplicate launch ID")
                self.launches.add(key)
                metrics["launches"] += 1
            elif kind == "eligible":
                key = (event["group"], event["allocation"])
                require(key not in self.allocations, "duplicate reward allocation")
                require(event["token"] in self.token_addresses and event["amount"] > 0, "unsupported allocation")
                self.allocations[key] = {"wallet": wallet, "token": event["token"], "amount": event["amount"],
                                         "eligible_at": timestamp, "first_claim_at": None, "received": 0}
                metrics["eligible_claims"] += 1
            elif kind == "claim":
                key = (event["group"], event["allocation"])
                allocation = self.allocations.get(key)
                require(allocation is not None, "claim without eligibility history")
                require(allocation["wallet"] == wallet and allocation["token"] == event["token"],
                        "claim beneficiary/token mismatch")
                require(allocation["received"] + event["amount"] <= allocation["amount"], "overclaimed allocation")
                require(timestamp >= allocation["eligible_at"], "negative claim latency")
                if allocation["first_claim_at"] is None:
                    allocation["first_claim_at"] = timestamp
                    delay = timestamp - allocation["eligible_at"]
                    metrics["claimed_claims"] += 1
                    metrics["total_claim_delay"] += delay
                    metrics["max_claim_delay"] = max(metrics["max_claim_delay"], delay)
                allocation["received"] += event["amount"]
            elif kind == "interact":
                key = (wallet, event["app"], log["transactionHash"])
                if key not in self.interactions:
                    self.interactions.add(key)
                    self.apps[wallet].add(event["app"])
                    metrics["interactions"] += 1
                    metrics["distinct_apps"] = len(self.apps[wallet])

    def reports(self, balance_reader):
        rows = []
        for wallet in sorted(self.active_seats):
            tokens = []
            for policy in self.policy.tokens:
                token = policy["address"]
                portfolio = dict(self.portfolios[(wallet, token)])
                portfolio["balance"] = balance_reader(token, wallet)
                tokens.append({"token": token, **portfolio})
            row = {"wallet": wallet, "metrics": dict(self.metrics[wallet]), "tokens": tokens,
                   "apps": sorted(self.apps[wallet]), "claims": []}
            for (group, allocation_id), allocation in sorted(self.allocations.items()):
                if allocation["wallet"] == wallet:
                    row["claims"].append({"group": group, "allocation": allocation_id, **allocation})
            score, retention, support = score_row(row, self.policy)
            row.update(score=score, retention_bps=retention, support_bps=support)
            rows.append(row)
        rows.sort(key=lambda row: (-row["score"], int(row["wallet"], 16)))
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            row["tier"] = ("Observer", "Contributor", "Chad", "GigaChad")[min(row["score"] // 2500, 3)]
        return rows


def score_row(row, policy):
    address(row["wallet"])
    metrics, tokens = row["metrics"], row["tokens"]
    for name, bits in zip(METRICS, (32, 32, 32, 32, 64, 64, 32, 16)):
        uint(metrics[name], bits)
    require(metrics["active_seats"] > 0 and metrics["claimed_claims"] <= metrics["eligible_claims"], "invalid metrics")
    claims, delay, maximum = metrics["claimed_claims"], metrics["total_claim_delay"], metrics["max_claim_delay"]
    require(metrics["distinct_apps"] <= metrics["interactions"] and maximum <= delay <= claims * maximum,
            "invalid claim delay or app totals")
    require(len(tokens) == len(policy.tokens), "token report length mismatch")
    retention, support = [], []
    for token, configured in zip(tokens, policy.tokens):
        require(address(token["token"]) == configured["address"], "token report order mismatch")
        for name in AMOUNTS:
            uint(token[name], 128)
        require(token["reward_held"] + token["reward_sold"] + token["reward_other_out"] == token["claimed"]
                and token["reward_held"] <= token["balance"] and token["reward_sold"] <= token["sold"]
                and token["reward_other_out"] <= token["other_out"], "inconsistent reward attribution/balance")
        if token["claimed"]:
            retention.append(token["reward_held"] * 10000 // token["claimed"])
        target = configured["support_target"]
        support.append(min(token["bought"], target) * 10000 // target)
    require(bool(claims) == bool(retention), "claims/token report mismatch")
    retention_bps = sum(retention) // len(retention) if retention else 0
    support_bps = sum(support) // len(support)
    speed = 1500 * (WINDOW - min(delay // claims, WINDOW)) * claims // (WINDOW * metrics["eligible_claims"]) if claims else 0
    score = min(metrics["launches"], 30) * 100 + speed + retention_bps * 3000 // 10000
    score += support_bps * 1500 // 10000 + min(metrics["distinct_apps"], 10) * 100
    return score, retention_bps, support_bps


def event_requests(policy, seat_pass):
    by_emitter = defaultdict(set)
    for (emitter, topic), schemas in policy.schemas.items():
        if any((schema["kind"] in ("activate", "deactivate")) == seat_pass for schema in schemas):
            by_emitter[emitter].add(topic)
    return [{"address": emitter, "topics": [sorted(topics)]} for emitter, topics in sorted(by_emitter.items())]


def transactions(rpc, requests, start, end, chunk_size, evidence):
    for first in range(start, end + 1, chunk_size):
        last = min(first + chunk_size - 1, end)
        logs = {}
        for request in requests:
            result = rpc.call("eth_getLogs", [{**request, "fromBlock": hex(first), "toBlock": hex(last)}])
            require(isinstance(result, list), "malformed log result")
            for log in result:
                height = uint(log["blockNumber"], 64)
                require(first <= height <= last and log.get("removed") is False, "removed/out-of-range log")
                address(log["address"])
                hash32(log["blockHash"])
                hash32(log["transactionHash"])
                require(log["topics"] and all(re.fullmatch(r"0x[0-9a-fA-F]{64}", t) for t in log["topics"]),
                        "malformed log topics")
                require(re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", log["data"]), "malformed log data")
                key = (height, uint(log["transactionIndex"]), uint(log["logIndex"]))
                require(key not in logs or logs[key] == log, "conflicting duplicate log")
                logs[key] = log
        ordered = sorted(logs.items())
        for height, group in itertools.groupby(ordered, key=lambda item: item[0][0]):
            header = rpc.call("eth_getBlockByNumber", [hex(height), False])
            require(header is not None and uint(header["number"]) == height, "missing block header")
            block_hash, timestamp = hash32(header["hash"]), uint(header["timestamp"], 64)
            items = list(group)
            for _, log in items:
                require(log["blockHash"].lower() == block_hash, "reorg or inconsistent log block hash")
                evidence.update(canonical(log) + b"\n")
            for _, transaction in itertools.groupby(items, key=lambda item: item[0][1]):
                batch = [item[1] for item in transaction]
                require(len({item["transactionHash"] for item in batch}) == 1, "transaction hash/index mismatch")
                yield batch, timestamp


def rpc_word(rpc, contract, data, block="latest", sender=None):
    call = {"to": contract, "data": data}
    if sender:
        call["from"] = sender
    result = rpc.call("eth_call", [call, block])
    require(isinstance(result, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", result), "expected one ABI return word")
    return uint(result)


def scan(policy, rpc, chunk_size=2000):
    require(uint(rpc.call("eth_chainId", [])) == 1, "RPC is not Ethereum mainnet")
    require(1 <= chunk_size <= 100000, "invalid RPC block chunk size")
    final = rpc.call("eth_getBlockByNumber", ["finalized", False])
    require(isinstance(final, dict), "RPC must support finalized blocks")
    height, timestamp, block_hash = uint(final["number"], 64), uint(final["timestamp"], 64), hash32(final["hash"])
    require(policy.start <= height, "start block is after finalized block")
    pinned = {"blockHash": block_hash, "requireCanonical": True}
    emitters = {key[0] for key in policy.schemas}
    for source in {policy.nft, *emitters, *(t["address"] for t in policy.tokens)}:
        require(rpc.call("eth_getCode", [source, pinned]) not in ("0x", "0x0", None), "source has no code at snapshot")
    evidence = hashlib.sha256(b"IMDChadBoard-indexer-v1\n")
    ledger = Ledger(policy)
    requests = event_requests(policy, True) + [{"address": policy.nft, "topics": [TRANSFER]}]
    for logs, _ in transactions(rpc, requests, policy.start, height, chunk_size, evidence):
        ledger.observe_seats(logs)
    ledger.finish_census()
    if ledger.active_seats:
        requests = event_requests(policy, False)
        wallets = sorted(ledger.active_seats)
        tokens = [t["address"] for t in policy.tokens]
        # Filter Transfers by the final census wallets; unrelated token holders never enter the ledger.
        for offset in range(0, len(wallets), 100):
            topics = ["0x" + word(wallet) for wallet in wallets[offset:offset + 100]]
            requests.extend([{"address": tokens, "topics": [TRANSFER, topics]},
                             {"address": tokens, "topics": [TRANSFER, None, topics]}])
        for logs, when in transactions(rpc, requests, policy.start, height, chunk_size, evidence):
            ledger.observe_activity(logs, when)
    rows = ledger.reports(lambda token, wallet: rpc_word(rpc, token, "0x70a08231" + word(wallet), pinned))
    after = rpc.call("eth_getBlockByNumber", [hex(height), False])
    require(after is not None and hash32(after["hash"]) == block_hash, "snapshot reorged during scan")
    return {"version": 1, "chain_id": 1, "methodology_hash": policy.hash, "policy": policy.raw,
            "block": {"number": height, "timestamp": timestamp, "hash": block_hash},
            "summary": {"total_seats": len(ledger.owners), "activated_seats": len(ledger.activated), "wallet_count": len(rows)},
            "source_log_digest": "0x" + evidence.hexdigest(), "wallets": rows}


def calldata(signature, *args):
    try:
        result = subprocess.run(["cast", "calldata", signature, *map(str, args)], check=True,
                                capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AuditError(f"cast calldata failed: {type(exc).__name__}") from None
    encoded = result.stdout.strip()
    require(re.fullmatch(r"0x[0-9a-fA-F]+", encoded), "cast returned malformed calldata")
    return encoded


def tuple_text(values):
    return "(" + ",".join(map(str, values)) + ")"


def token_text(row):
    return "[" + ",".join(tuple_text(t[name] for name in AMOUNTS) for t in row["tokens"]) + "]"


def row_text(row):
    return tuple_text((row["wallet"], tuple_text(row["metrics"][name] for name in METRICS), token_text(row)))


def prepare(report, rpc, board, batch_size=10):
    board = address(board)
    policy = Policy(report["policy"])
    require(report["version"] == 1 and report["chain_id"] == 1 and report["methodology_hash"] == policy.hash,
            "report policy hash/version mismatch")
    require(1 <= batch_size <= 20, "batch size must be 1..20")
    require(uint(rpc.call("eth_chainId", [])) == 1, "RPC is not Ethereum mainnet")
    get = lambda signature: rpc_word(rpc, board, calldata(signature))
    require(get("pendingEpoch()") == 0, "board has an unfinished epoch; finish or abort it first")
    require(get("seatNFT()") == int(policy.nft, 16), "board NFT differs from policy")
    require(get("methodologyHash()") == int(policy.hash, 16), "board methodology differs from report")
    reporter = get("reporter()")
    require(reporter != 0, "reporter is not configured")
    reporter = "0x" + f"{reporter:040x}"
    configured = rpc.call("eth_call", [{"to": board, "data": calldata("tokenPolicies()")}, "latest"])
    expected = "0x" + word(32) + word(len(policy.tokens)) + "".join(
        word(token["address"]) + word(token["support_target"]) for token in policy.tokens)
    require(configured.lower() == expected, "board token policies differ from report")
    configuration = get("configuration()")
    epoch = get("epochCount()") + 1
    final = rpc.call("eth_getBlockByNumber", ["finalized", False])
    block = report["block"]
    observed = rpc.call("eth_getBlockByNumber", [hex(uint(block["number"], 64)), False])
    require(final is not None and uint(final["number"]) >= block["number"] and observed is not None
            and hash32(observed["hash"]) == block["hash"] and uint(observed["timestamp"]) == block["timestamp"],
            "report block is no longer canonical/finalized")
    rows, summary = report["wallets"], report["summary"]
    require(summary["wallet_count"] == len(rows) and sum(r["metrics"]["active_seats"] for r in rows)
            == summary["activated_seats"] <= summary["total_seats"], "report census mismatch")
    require(len({address(r["wallet"]) for r in rows}) == len(rows), "duplicate report wallet")
    require(rows == sorted(rows, key=lambda row: (-row["score"], int(row["wallet"], 16))), "report order mismatch")
    for rank, row in enumerate(rows, 1):
        score, retention, support = score_row(row, policy)
        require(row["rank"] == rank and (row["score"], row["retention_bps"], row["support_bps"])
                == (score, retention, support), "report score/rank mismatch")
        require(row["metrics"]["max_claim_delay"] <= block["timestamp"], "claim predates chain time")
        data = calldata(f"previewScore({METRIC_ABI},{TOKEN_ABI}[])",
                        tuple_text(row["metrics"][key] for key in METRICS), token_text(row))
        preview = rpc.call("eth_call", [{"to": board, "data": data}, "latest"])
        require(preview.lower() == "0x" + word(score) + word(retention) + word(support), "on-chain score differs")
    report_hash = digest(report)
    snapshot = tuple_text((block["number"], block["timestamp"], block["hash"], summary["total_seats"],
                           summary["activated_seats"], len(rows), report_hash, configuration))
    begin = calldata(BEGIN_ABI, snapshot)
    require(rpc_word(rpc, board, begin, sender=reporter) == epoch, "beginEpoch simulation differs")
    calls = [{"step": "begin", "data": begin}]
    for offset in range(0, len(rows), batch_size):
        data = calldata(f"appendWallets(uint64,{ROW_ABI}[])", epoch,
                        "[" + ",".join(row_text(row) for row in rows[offset:offset + batch_size]) + "]")
        calls.append({"step": f"append-{offset}", "data": data})
    calls.append({"step": "finalize", "data": calldata("finalizeEpoch(uint64)", epoch)})
    for call in calls:
        call.update(to=board, value="0", chainId=1)
    return {"epoch": epoch, "configuration": configuration, "reporter": reporter,
            "evidence_hash": report_hash, "calls": calls}


def query(rpc, board, wallet=None, epoch=None, offset=0, limit=20):
    """Decode board ABI into exact-integer JSON for a single wallet or a leaderboard page."""
    board = address(board)
    require(uint(rpc.call("eth_chainId", [])) == 1, "RPC is not Ethereum mainnet")
    # Pin all reads to the same block, so publication during a multi-call query cannot mix epochs.
    latest = rpc.call("eth_getBlockByNumber", ["latest", False])
    require(latest is not None, "missing current block")
    pinned = {"blockHash": hash32(latest["hash"]), "requireCanonical": True}

    def read(signature, *args):
        encoded = rpc.call("eth_call", [{"to": board, "data": calldata(signature, *args)}, pinned])
        require(isinstance(encoded, str) and re.fullmatch(r"0x(?:[0-9a-fA-F]{64})*", encoded), "malformed board return")
        return [int(encoded[i:i + 64], 16) for i in range(2, len(encoded), 64)]

    def array(words, width):
        require(len(words) >= 2 and words[0] == 32 and len(words) == 2 + words[1] * width, "invalid ABI array")
        return [words[i:i + width] for i in range(2, len(words), width)]

    def scalar(signature):
        values = read(signature)
        require(len(values) == 1, "expected one board return word; check the deployment address")
        return values[0]

    if epoch is None:
        epoch = scalar("latestEpoch()")
    uint(epoch, 64)
    require(epoch != 0, "no published snapshot yet")
    meta = read("getEpoch(uint64)", epoch)
    require(len(meta) == 17 and meta[0] == 2, "epoch is not published")
    current = meta[9] == scalar("configuration()")
    stale = uint(latest["timestamp"]) - meta[2] > meta[10] or not current
    result = {"epoch": epoch, "as_of_block": meta[1], "as_of_timestamp": meta[2],
              "block_hash": "0x" + word(meta[3]), "total_seats": meta[4], "activated_seats": meta[5],
              "wallet_count": meta[6], "evidence_hash": "0x" + word(meta[7]), "configuration": meta[9],
              "methodology_hash": "0x" + word(meta[16]), "stale": stale, "current_configuration": current}
    tiers = ("Observer", "Contributor", "Chad", "GigaChad")
    if wallet is not None:
        wallet = address(wallet)
        rating = read("walletAt(uint64,address)", epoch, wallet)
        require(len(rating) == 19 and rating[6] < len(tiers), "invalid wallet rating")
        metrics = dict(zip(METRICS, rating[7:15]))
        policies = array(read("epochTokenPolicies(uint64)", epoch), 2)
        portfolio = array(read("walletTokens(uint64,address)", epoch, wallet), 8)
        require(len(portfolio) == (len(policies) if rating[5] else 0), "invalid portfolio length")
        result["wallet"] = {"address": wallet, "found": bool(rating[5]), "tier": tiers[rating[6]],
                            "rank": rating[15], "score": rating[16], "retention_bps": rating[17],
                            "support_bps": rating[18], "metrics": metrics,
                            "average_first_claim_delay": metrics["total_claim_delay"] // metrics["claimed_claims"]
                            if metrics["claimed_claims"] else None,
                            "tokens": [{"token": "0x" + f"{policy[0]:040x}", **dict(zip(AMOUNTS, amounts))}
                                       for policy, amounts in zip(policies, portfolio)]}
    else:
        require(0 <= offset < 2**32 and 1 <= limit <= 100, "invalid leaderboard pagination")
        rows = array(read("leaderboard(uint64,uint32,uint32)", epoch, offset, limit), 5)
        result["leaderboard"] = [{"wallet": "0x" + f"{row[0]:040x}", "rank": row[1], "score": row[2],
                                  "tier": tiers[row[3]], "active_seats": row[4]} for row in rows]
        result["next_offset"] = offset + len(rows) if offset + len(rows) < meta[6] else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("policy-hash", help="validate and hash a deployment-specific indexing policy")
    inspect.add_argument("--policy", required=True)
    collect = commands.add_parser("scan", help="read finalized chain activity; produce canonical JSON")
    collect.add_argument("--policy", required=True)
    collect.add_argument("--rpc", required=True)
    collect.add_argument("--output", required=True)
    collect.add_argument("--chunk-size", type=int, default=2000)
    package = commands.add_parser("prepare", help="validate a report against the board; produce unsigned calldata")
    package.add_argument("--report", required=True)
    package.add_argument("--rpc", required=True)
    package.add_argument("--board", required=True)
    package.add_argument("--output", required=True)
    package.add_argument("--batch-size", type=int, default=10)
    lookup = commands.add_parser("query", help="read a wallet rating or leaderboard page, without an indexer")
    lookup.add_argument("--rpc", required=True)
    lookup.add_argument("--board", required=True)
    lookup.add_argument("--wallet")
    lookup.add_argument("--epoch", type=int)
    lookup.add_argument("--offset", type=int, default=0)
    lookup.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    try:
        if args.command == "policy-hash":
            print(Policy(json.loads(Path(args.policy).read_text())).hash)
            return 0
        if args.command == "query":
            print(json.dumps(query(Rpc(args.rpc), args.board, args.wallet, args.epoch, args.offset, args.limit), indent=2))
            return 0
        if args.command == "scan":
            policy = Policy(json.loads(Path(args.policy).read_text()))
            result = scan(policy, Rpc(args.rpc), args.chunk_size)
        else:
            result = prepare(json.loads(Path(args.report).read_text()), Rpc(args.rpc), args.board, args.batch_size)
        Path(args.output).write_bytes(canonical(result) + b"\n")
        print(f"Wrote {args.output}; SHA-256 of canonical JSON: {digest(result)}")
        return 0
    except (AuditError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Refusing report: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
