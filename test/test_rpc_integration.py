"""Real local EVM: source logs -> scanner -> unsigned calldata -> board -> reader.

All transactions target a newly started loopback Anvil, using its unlocked test
accounts. No keys, environment variables, live networks or external services.
"""

import copy
import json
from pathlib import Path
import socket
import subprocess
import time
import unittest
import urllib.request

from test_indexer import imd

ROOT = Path(__file__).resolve().parents[1]


class RpcIntegrationTest(unittest.TestCase):
    def test_real_logs_publish_and_query(self):
        subprocess.run(["forge", "build", "--silent"], cwd=ROOT, check=True, capture_output=True)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        node = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", str(port), "--chain-id", "1", "--silent"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            self.url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    accounts = self.local("eth_accounts", [])
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                self.fail("local Anvil did not start")
            owner, reporter, alice, bob, friend = accounts[:5]
            rpc = imd.Rpc(self.url)
            board = self.deploy("IMDChadBoard.sol", "IMDChadBoard", owner, imd.word(owner))
            nft = self.deploy("IndexerSources.sol", "SeatTestSource", owner)
            token = self.deploy("IndexerSources.sol", "TokenTestSource", owner)
            activity = self.deploy("IndexerSources.sol", "ActivityTestSource", owner, imd.word(token))
            policy = self.make_policy(nft, token, activity)
            with self.assertRaises(imd.AuditError):
                imd.query(rpc, board)
            self.send(owner, board, imd.calldata("setSources(address,bytes32)", nft, policy.hash))
            self.send(owner, board, imd.calldata("setReporter(address)", reporter))
            self.send(owner, board, imd.calldata("setTokenPolicies((address,uint128)[])", f"[({token},100)]"))
            for seat, wallet in [(41, alice), (97, bob), (1001, alice)]:
                self.send(owner, nft, imd.calldata("mint(uint256,address)", seat, wallet))
            for seat, wallet in [(41, alice), (97, bob)]:
                self.send(owner, nft, imd.calldata("activate(uint256,address)", seat, wallet))
            self.send(owner, token, imd.calldata("mint(address,uint256)", activity, 1000))
            self.send(owner, activity, imd.calldata("launch(address,uint256)", alice, 101))
            self.send(owner, activity, imd.calldata("eligible(address,uint256,uint256)", alice, 12, 100))
            self.send(owner, activity, imd.calldata("eligible(address,uint256,uint256)", alice, 13, 100))
            self.local("evm_increaseTime", [600])
            self.send(owner, activity, imd.calldata("claim(address,uint256,uint256)", alice, 12, 100))
            self.send(owner, activity, imd.calldata("buy(address,uint256)", alice, 50))
            self.send(owner, activity, imd.calldata("sell(address,uint256)", alice, 30))
            self.send(owner, token, imd.calldata("move(address,address,uint256)", alice, friend, 20))
            self.send(owner, activity, imd.calldata("interact(address)", alice))
            self.local("anvil_mine", ["0x80"])
            report = imd.scan(policy, rpc, chunk_size=7)
            self.assertEqual(report["summary"], {"total_seats": 3, "activated_seats": 2, "wallet_count": 2})
            alice_row = next(row for row in report["wallets"] if row["wallet"] == alice)
            self.assertEqual(alice_row["metrics"]["claimed_claims"], 1)
            self.assertGreaterEqual(alice_row["metrics"]["total_claim_delay"], 600)
            self.assertEqual(alice_row["tokens"][0]["reward_held"], 50)
            self.assertEqual(alice_row["tokens"][0]["balance"], 100)
            tampered = copy.deepcopy(report)
            tampered["wallets"][0]["score"] += 1
            with self.assertRaisesRegex(imd.AuditError, "score/rank mismatch"):
                imd.prepare(tampered, rpc, board)
            package = imd.prepare(report, rpc, board, batch_size=1)
            self.assertEqual(package["epoch"], 1)
            self.assertEqual(len(package["calls"]), 4)
            for call in package["calls"][:-1]:
                self.send(reporter, board, call["data"])
            with self.assertRaisesRegex(imd.AuditError, "no published"):
                imd.query(rpc, board)
            self.send(reporter, board, package["calls"][-1]["data"])
            ranking = imd.query(rpc, board, limit=1)
            self.assertEqual(ranking["leaderboard"][0]["wallet"], alice)
            self.assertEqual(ranking["next_offset"], 1)
            second = imd.query(rpc, board, offset=1)
            self.assertEqual(second["leaderboard"][0]["wallet"], bob)
            rating = imd.query(rpc, board, wallet=alice)
            self.assertEqual(rating["wallet"]["score"], alice_row["score"])
            self.assertEqual(rating["wallet"]["tokens"], alice_row["tokens"])
            self.assertEqual(rating["evidence_hash"], imd.digest(report))
            self.assertFalse(rating["stale"])
            self.assertFalse(imd.query(rpc, board, wallet=friend)["wallet"]["found"])
            with self.assertRaises(imd.AuditError):
                imd.prepare(report, rpc, board)  # Same block cannot be replayed as a new epoch.
            self.send(owner, board, imd.calldata("setMaxAge(uint64)", 86400))
            old = imd.query(rpc, board, wallet=alice, epoch=1)
            self.assertTrue(old["stale"])
            self.assertFalse(old["current_configuration"])
        finally:
            node.terminate()
            try:
                node.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                node.kill()
                node.communicate()

    def local(self, method, params):
        # Intentionally separate from the production read-only RPC client.
        request = urllib.request.Request(self.url, data=json.dumps({"jsonrpc": "2.0", "id": 1,
                                         "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
        if "error" in result:
            raise AssertionError(result["error"])
        return result["result"]

    def send(self, sender, to, data):
        tx = {"from": sender, "data": data, "gas": "0x1c9c380"}
        if to:
            tx["to"] = to
        tx_hash = self.local("eth_sendTransaction", [tx])
        receipt = None
        for _ in range(100):
            receipt = self.local("eth_getTransactionReceipt", [tx_hash])
            if receipt is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(receipt, "local transaction was not mined")
        self.assertEqual(receipt["status"], "0x1")
        return receipt

    def deploy(self, file, name, owner, args=""):
        artifact = json.loads((ROOT / "out" / file / f"{name}.json").read_text())
        return self.send(owner, None, artifact["bytecode"]["object"] + args)["contractAddress"]

    def make_policy(self, nft, token, activity):
        policy = {"version": 1, "chain_id": 1, "start_block": 0, "seat_nft": nft,
                  "seat_wallet_mode": "activation", "activation_survives_transfer": True,
                  "tokens": [{"address": token, "support_target": 100}], "events": []}
        descriptions = [
            ("activate", nft, "Activated(uint256,address)", {"seat": "topic:1", "wallet": "data:0"}),
            ("deactivate", nft, "Deactivated(uint256)", {"seat": "topic:1"}),
            ("launch", activity, "Launched(address,uint256)", {"wallet": "topic:1", "id": "data:0"}),
            ("eligible", activity, "Eligible(address,uint256,address,uint256)",
             {"wallet": "topic:1", "allocation": "data:0", "token": "data:1", "amount": "data:2"}),
            ("claim", activity, "Claimed(address,uint256,address,uint256,address)",
             {"wallet": "topic:1", "allocation": "data:0", "token": "data:1", "amount": "data:2", "counterparty": "data:3"}),
            ("buy", activity, "Bought(address,address,uint256,address)",
             {"wallet": "topic:1", "token": "data:0", "amount": "data:1", "counterparty": "data:2"}),
            ("sell", activity, "Sold(address,address,uint256,address)",
             {"wallet": "topic:1", "token": "data:0", "amount": "data:1", "counterparty": "data:2"}),
            ("interact", activity, "Interacted(address)", {"wallet": "topic:1"}),
        ]
        for kind, emitter, signature, fields in descriptions:
            topic = subprocess.run(["cast", "keccak", signature], check=True, capture_output=True, text=True).stdout.strip()
            descriptor = {"kind": kind, "address": emitter, "topic0": topic, "fields": fields}
            if kind in ("launch", "eligible", "claim"):
                descriptor["group"] = "launches" if kind == "launch" else "allocations"
            if kind == "interact":
                descriptor["app"] = "local-ecosystem-app"
            policy["events"].append(descriptor)
        return imd.Policy(policy)


if __name__ == "__main__":
    unittest.main()
