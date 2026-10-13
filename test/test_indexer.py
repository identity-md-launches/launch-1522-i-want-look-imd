"""Offline semantic and RPC tests. Run: python3 -m unittest discover -s test -p 'test_*.py'."""

import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "tools" / "imd_indexer.py"
spec = importlib.util.spec_from_file_location("imd_indexer", MODULE)
imd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imd)


def addr(number):
    return "0x" + f"{number:040x}"


NFT, TOKEN, SOURCE, VENUE, ALICE, BOB, CAROL = map(addr, range(1, 8))
BASE = 100 * 86400
FIELD_ORDER = {
    "activate": ["seat", "wallet"], "deactivate": ["seat"], "launch": ["wallet", "id"],
    "eligible": ["wallet", "allocation", "token", "amount"],
    "claim": ["wallet", "allocation", "token", "amount", "counterparty"],
    "buy": ["wallet", "token", "amount", "counterparty"],
    "sell": ["wallet", "token", "amount", "counterparty"], "interact": ["wallet"],
}
TOPICS = {kind: "0x" + hashlib.sha256(kind.encode()).hexdigest() for kind in FIELD_ORDER}


def policy_raw(mode="activation", survives=True):
    result = {"version": 1, "chain_id": 1, "start_block": 1, "seat_nft": NFT,
              "seat_wallet_mode": mode, "activation_survives_transfer": survives,
              "tokens": [{"address": TOKEN, "support_target": "100"}], "events": []}
    for kind, fields in FIELD_ORDER.items():
        if kind == "activate" and mode == "owner":
            fields = ["seat"]
        descriptor = {"kind": kind, "address": SOURCE, "topic0": TOPICS[kind],
                      "fields": {name: f"data:{i}" for i, name in enumerate(fields)}}
        if kind in ("launch", "eligible", "claim"):
            descriptor["group"] = "launch-v1" if kind == "launch" else "rewards-v1"
        if kind == "interact":
            descriptor["app"] = "ecosystem-app"
        result["events"].append(descriptor)
    return result


def block_hash(height):
    return "0x" + imd.word(10000 + height)


def log_base(height, index, emitter, topics, data, transaction=0):
    return {"address": emitter, "topics": topics, "data": data, "blockNumber": hex(height),
            "blockHash": block_hash(height), "transactionHash": "0x" + imd.word(height * 100 + transaction),
            "transactionIndex": hex(transaction), "logIndex": hex(index), "removed": False}


def event(kind, height, index=0, transaction=0, **values):
    fields = FIELD_ORDER[kind]
    return log_base(height, index, SOURCE, [TOPICS[kind]], "0x" + "".join(imd.word(values[f]) for f in fields), transaction)


def transfer(height, index, origin, destination, amount, nft=False, transaction=0):
    topics = [imd.TRANSFER, "0x" + imd.word(origin), "0x" + imd.word(destination)]
    if nft:
        topics.append("0x" + imd.word(amount))
    return log_base(height, index, NFT if nft else TOKEN, topics, "0x" if nft else "0x" + imd.word(amount), transaction)


class FakeRpc:
    def __init__(self, logs, balances=None, end=12):
        self.logs = logs
        self.balances = balances or {}
        self.end = end
        self.calls = []
        self.chain = 1
        self.reorg = False

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain)
        if method == "eth_getCode":
            return "0x00"
        if method == "eth_getBlockByNumber":
            height = self.end if params[0] == "finalized" else int(params[0], 16)
            return {"number": hex(height), "timestamp": hex(BASE + height * 100),
                    "hash": block_hash(height + 1 if self.reorg and height == self.end and params[0] != "finalized" else height)}
        if method == "eth_getLogs":
            query = params[0]
            addresses = query["address"] if isinstance(query["address"], list) else [query["address"]]
            result = []
            for log in self.logs:
                if not (int(query["fromBlock"], 16) <= int(log["blockNumber"], 16) <= int(query["toBlock"], 16)):
                    continue
                if log["address"] not in addresses:
                    continue
                valid = True
                for i, pattern in enumerate(query["topics"]):
                    if pattern is None:
                        continue
                    allowed = pattern if isinstance(pattern, list) else [pattern]
                    if i >= len(log["topics"]) or log["topics"][i] not in allowed:
                        valid = False
                if valid:
                    result.append(log)
            return result
        if method == "eth_call":
            call, pinned = params
            if not isinstance(pinned, dict) or pinned.get("blockHash") != block_hash(self.end) or not pinned["requireCanonical"]:
                raise AssertionError("balance must be read at the canonical snapshot hash")
            wallet = addr(int(call["data"][10:], 16))
            return "0x" + imd.word(self.balances.get((call["to"], wallet), 0))
        raise AssertionError(method)


def history():
    return [
        transfer(1, 0, imd.ZERO, ALICE, 41, nft=True),
        transfer(1, 1, imd.ZERO, BOB, 97, nft=True),
        transfer(1, 2, imd.ZERO, ALICE, 1001, nft=True),
        event("activate", 2, 0, seat=41, wallet=ALICE),
        event("activate", 2, 1, seat=97, wallet=BOB),
        event("launch", 3, wallet=ALICE, id=101),
        event("eligible", 4, 0, wallet=ALICE, allocation=12, token=TOKEN, amount=100),
        event("eligible", 4, 1, wallet=ALICE, allocation=13, token=TOKEN, amount=200),
        transfer(5, 0, SOURCE, ALICE, 60),
        event("claim", 5, 1, wallet=ALICE, allocation=12, token=TOKEN, amount=60, counterparty=SOURCE),
        transfer(6, 0, SOURCE, ALICE, 40),
        event("claim", 6, 1, wallet=ALICE, allocation=12, token=TOKEN, amount=40, counterparty=SOURCE),
        transfer(7, 0, VENUE, ALICE, 50),
        event("buy", 7, 1, wallet=ALICE, token=TOKEN, amount=50, counterparty=VENUE),
        transfer(8, 0, ALICE, VENUE, 30),
        event("sell", 8, 1, wallet=ALICE, token=TOKEN, amount=30, counterparty=VENUE),
        transfer(9, 0, ALICE, CAROL, 20),
        transfer(10, 0, CAROL, ALICE, 100),
        event("interact", 11, 0, wallet=ALICE),
        event("interact", 11, 1, wallet=ALICE),
    ]


class IndexerTest(unittest.TestCase):
    def test_complete_finalized_scan_measures_all_requested_dimensions(self):
        rpc = FakeRpc(history(), {(TOKEN, ALICE): 200})
        report = imd.scan(imd.Policy(policy_raw()), rpc, chunk_size=3)
        self.assertEqual(report["summary"], {"total_seats": 3, "activated_seats": 2, "wallet_count": 2})
        alice, bob = report["wallets"]
        self.assertEqual(alice["wallet"], ALICE)
        self.assertEqual(alice["metrics"], dict(zip(imd.METRICS, [1, 1, 2, 1, 100, 100, 1, 1])))
        self.assertEqual(alice["tokens"][0], {"token": TOKEN, **dict(zip(imd.AMOUNTS, [100, 50, 30, 20, 50, 30, 20, 200]))})
        self.assertEqual(alice["score"], 3199)
        self.assertEqual(alice["claims"][0]["received"], 100)
        self.assertEqual(alice["claims"][0]["first_claim_at"], BASE + 500)
        self.assertIsNone(alice["claims"][1]["first_claim_at"])
        self.assertEqual(bob["rank"], 2)
        self.assertEqual(bob["score"], 0)
        self.assertEqual(report["methodology_hash"], imd.digest(policy_raw()))
        # Different query chunk boundaries produce the exact same evidence and report.
        second = imd.scan(imd.Policy(policy_raw()), FakeRpc(history(), {(TOKEN, ALICE): 200}), chunk_size=100)
        self.assertEqual(report, second)

    def test_transfer_can_follow_owner_or_keep_explicit_activated_wallet(self):
        logs = history()[:5] + [transfer(3, 0, ALICE, CAROL, 41, nft=True)]
        associated = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        self.assertEqual({r["wallet"] for r in associated["wallets"]}, {ALICE, BOB})
        owner = imd.scan(imd.Policy(policy_raw("owner")), FakeRpc(logs))
        self.assertEqual({r["wallet"] for r in owner["wallets"]}, {BOB, CAROL})
        deactivated = imd.scan(imd.Policy(policy_raw(survives=False)), FakeRpc(logs))
        self.assertEqual(deactivated["summary"]["activated_seats"], 1)

    def test_burn_deactivation_rebinding_and_multiple_seats_are_counted_once(self):
        logs = history()[:5] + [event("activate", 3, 0, seat=1001, wallet=ALICE)]
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        self.assertEqual(report["summary"]["activated_seats"], 3)
        self.assertEqual(next(r for r in report["wallets"] if r["wallet"] == ALICE)["metrics"]["active_seats"], 2)
        logs += [event("activate", 4, 0, seat=41, wallet=CAROL),
                 event("deactivate", 5, 0, seat=97), transfer(6, 0, ALICE, imd.ZERO, 1001, nft=True)]
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        self.assertEqual(report["summary"], {"total_seats": 2, "activated_seats": 1, "wallet_count": 1})
        self.assertEqual(report["wallets"][0]["wallet"], CAROL)

    def test_ordinary_outgoing_pool_transfer_is_not_a_sale(self):
        logs = [item for item in history() if item["topics"][0] != TOPICS["sell"]]
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs, {(TOKEN, ALICE): 200}))
        portfolio = report["wallets"][0]["tokens"][0]
        self.assertEqual(portfolio["sold"], 0)
        self.assertEqual(portfolio["reward_sold"], 0)
        self.assertEqual(portfolio["reward_other_out"], 50)
        self.assertEqual(portfolio["other_out"], 50)

    def test_gifts_and_self_transfers_do_not_increase_support(self):
        logs = history() + [transfer(12, 0, ALICE, ALICE, 150)]
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs, {(TOKEN, ALICE): 200}))
        p = report["wallets"][0]["tokens"][0]
        self.assertEqual(p["bought"], 50)
        self.assertEqual(p["reward_held"], 50)
        self.assertEqual(p["other_out"], 20)

    def test_reward_disposals_are_not_reversed_by_repurchase(self):
        logs = history()[:13] + [transfer(7, 1, ALICE, VENUE, 100),
                                event("sell", 7, 2, wallet=ALICE, token=TOKEN, amount=100, counterparty=VENUE),
                                event("buy", 7, 3, wallet=ALICE, token=TOKEN, amount=50, counterparty=VENUE)]
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs, {(TOKEN, ALICE): 50}))
        p = report["wallets"][0]["tokens"][0]
        self.assertEqual(p["reward_held"], 0)
        self.assertEqual(p["reward_sold"], 100)
        self.assertEqual(p["bought"], 50)

    def test_rejects_missing_or_mismatched_transfer_and_double_classification(self):
        logs = [item for item in history() if not (item["blockNumber"] == "0x5" and item["logIndex"] == "0x0")]
        with self.assertRaisesRegex(imd.AuditError, "matching, unused"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        logs = history()
        logs[8]["data"] = "0x" + imd.word(59)
        with self.assertRaisesRegex(imd.AuditError, "matching, unused"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        logs = history() + [event("buy", 5, 2, wallet=ALICE, token=TOKEN, amount=60, counterparty=SOURCE)]
        with self.assertRaisesRegex(imd.AuditError, "matching, unused"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))

    def test_rejects_missing_history_overclaims_and_duplicate_ids(self):
        logs = [item for item in history() if item["topics"][0] != TOPICS["eligible"]]
        with self.assertRaisesRegex(imd.AuditError, "eligibility history"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))

        logs = history() + [transfer(12, 0, SOURCE, ALICE, 1),
                            event("claim", 12, 1, wallet=ALICE, allocation=12, token=TOKEN, amount=1, counterparty=SOURCE)]
        with self.assertRaisesRegex(imd.AuditError, "overclaimed"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        logs = history() + [event("launch", 12, wallet=ALICE, id=101)]
        with self.assertRaisesRegex(imd.AuditError, "duplicate launch"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        logs = history() + [event("eligible", 12, wallet=ALICE, allocation=12, token=TOKEN, amount=1)]
        with self.assertRaisesRegex(imd.AuditError, "duplicate reward allocation"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))

    def test_identical_transfers_cannot_silently_misattribute_reward_provenance(self):
        # Gift, disposal, then reward of the same amount from the same source:
        # choosing the first matching transfer would wrongly call the gift a reward.
        logs = history()[:8] + [transfer(5, 0, SOURCE, ALICE, 60), transfer(5, 1, ALICE, CAROL, 60),
                                transfer(5, 2, SOURCE, ALICE, 60),
                                event("claim", 5, 3, wallet=ALICE, allocation=12, token=TOKEN,
                                      amount=60, counterparty=SOURCE)]
        with self.assertRaisesRegex(imd.AuditError, "ambiguous activity Transfer"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))

    def test_rejects_rebasing_or_incomplete_token_history(self):
        with self.assertRaisesRegex(imd.AuditError, "attribution/balance"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(history(), {(TOKEN, ALICE): 49}))

    def test_unknown_emitters_do_not_count_as_activity(self):
        forged = event("launch", 12, wallet=ALICE, id=102)
        forged["address"] = VENUE
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(history() + [forged], {(TOKEN, ALICE): 200}))
        self.assertEqual(report["wallets"][0]["metrics"]["launches"], 1)

    def test_empty_census_and_unknown_seats(self):
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(history()[:3]))
        self.assertEqual(report["wallets"], [])
        self.assertEqual(report["summary"]["total_seats"], 3)
        with self.assertRaisesRegex(imd.AuditError, "nonexistent NFT"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc([event("activate", 2, seat=41, wallet=ALICE)]))
        with self.assertRaisesRegex(imd.AuditError, "NFT transfer history"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc([transfer(2, 0, ALICE, BOB, 41, nft=True)]))

    def test_rejects_removed_logs_wrong_chain_and_reorgs(self):
        logs = history()
        logs[0]["removed"] = True
        with self.assertRaisesRegex(imd.AuditError, "removed"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))
        rpc = FakeRpc([])
        rpc.chain = 2
        with self.assertRaisesRegex(imd.AuditError, "mainnet"):
            imd.scan(imd.Policy(policy_raw()), rpc)
        rpc = FakeRpc(history()[:5])
        rpc.reorg = True
        with self.assertRaisesRegex(imd.AuditError, "reorged"):
            imd.scan(imd.Policy(policy_raw()), rpc)
        logs = history()
        logs[0]["blockHash"] = block_hash(2)
        with self.assertRaisesRegex(imd.AuditError, "block hash"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs))

    def test_conflicting_duplicate_logs_fail_but_query_duplicates_are_deduplicated(self):
        logs = history()
        duplicate = copy.deepcopy(logs[0])
        duplicate["transactionHash"] = block_hash(444)
        with self.assertRaisesRegex(imd.AuditError, "conflicting duplicate"):
            imd.scan(imd.Policy(policy_raw()), FakeRpc(logs + [duplicate]))
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(logs + [logs[0]], {(TOKEN, ALICE): 200}))
        self.assertEqual(report["summary"]["total_seats"], 3)

    def test_tie_breaking_is_numeric_address_order(self):
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(history()[:5]))
        self.assertEqual([r["wallet"] for r in report["wallets"]], [ALICE, BOB])

    def test_policy_is_strict_and_has_no_deployment_defaults(self):
        for mutate in [lambda p: p.pop("seat_nft"), lambda p: p.update(chain_id=2),
                       lambda p: p.update(seat_nft=imd.ZERO), lambda p: p.update(tokens=[]),
                       lambda p: p.update(events=[]), lambda p: p["tokens"][0].update(support_target="0"),
                       lambda p: p["tokens"].append(p["tokens"][0]),
                       lambda p: p["events"][0]["fields"].update(seat="topic:4")]:
            raw = policy_raw()
            mutate(raw)
            with self.assertRaises(imd.AuditError):
                imd.Policy(raw)

    def test_decodes_constants_indexed_fields_and_mutually_exclusive_filters(self):
        raw = policy_raw()
        buy = next(e for e in raw["events"] if e["kind"] == "buy")
        buy["fields"]["counterparty"] = {"constant": VENUE}
        buy["fields"]["wallet"] = "topic:1"
        buy["where"] = [{"field": "data:2", "op": "gt", "value": 0}]
        log = event("buy", 7, wallet=ALICE, token=TOKEN, amount=50, counterparty=VENUE)
        log["topics"].append("0x" + imd.word(ALICE))
        decoded = imd.Policy(raw).decode(log)
        self.assertEqual(decoded["wallet"], ALICE)
        self.assertEqual(decoded["counterparty"], VENUE)
        duplicate = copy.deepcopy(buy)
        raw["events"].append(duplicate)
        with self.assertRaisesRegex(imd.AuditError, "ambiguous"):
            imd.Policy(raw).decode(log)
        duplicate["where"][0] = {"field": "data:2", "op": "eq", "value": 0}
        self.assertIsNotNone(imd.Policy(raw).decode(log))

    def test_rejects_overflow_malformed_address_and_non_read_rpc(self):
        with self.assertRaises(imd.AuditError):
            imd.uint(2**128, 128)
        with self.assertRaises(imd.AuditError):
            imd.uint(True)
        with self.assertRaises(imd.AuditError):
            imd.address("0x1234")
        with self.assertRaisesRegex(imd.AuditError, "non-read-only"):
            imd.Rpc("http://localhost:1").call("eth_sendTransaction", [])

    def test_abi_encoding_works_with_cast_without_network(self):
        report = imd.scan(imd.Policy(policy_raw()), FakeRpc(history(), {(TOKEN, ALICE): 200}))
        row = report["wallets"][0]
        encoded = imd.calldata(f"appendWallets(uint64,{imd.ROW_ABI}[])", 1, "[" + imd.row_text(row) + "]")
        self.assertTrue(encoded.startswith("0x"))
        self.assertEqual((len(encoded) - 10) % 64, 0)
        snapshot = imd.tuple_text((12, BASE + 1200, block_hash(12), 3, 2, 2, imd.digest(report), 3))
        self.assertEqual(len(imd.calldata(imd.BEGIN_ABI, snapshot)), 10 + 8 * 64)


if __name__ == "__main__":
    unittest.main()
