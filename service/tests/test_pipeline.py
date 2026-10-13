"""End-to-end test of the data service on a private loopback Anvil chain.

Requires Foundry (anvil, cast, forge). Run from the repository root:
    python3 -m unittest discover -s service/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "service"))

from chadboard import db  # noqa: E402
from chadboard.api import Api, make_server  # noqa: E402
from chadboard.config import Config  # noqa: E402
from chadboard.pipeline import refresh_with_retries  # noqa: E402
from chadboard.rpc import Rpc  # noqa: E402

KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # anvil account 0 (public test key)
A = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"
B = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
C = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"
D = "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65"
DAY = 86400


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(all(shutil.which(t) for t in ("anvil", "cast", "forge")), "Foundry tools are required")
class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="chadboard-test-"))
        subprocess.run(["forge", "build", "test/fixtures/IndexerSources.sol"], cwd=ROOT, check=True, capture_output=True)
        cls.port = free_port()
        cls.rpc_url = f"http://127.0.0.1:{cls.port}"
        cls.anvil = subprocess.Popen(["anvil", "--port", str(cls.port), "--silent"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rpc = Rpc([cls.rpc_url], timeout=10, attempts=20)
        deadline = time.time() + 30
        while True:
            try:
                rpc.chain_id()
                break
            except Exception:  # noqa: BLE001
                if time.time() > deadline:
                    raise
                time.sleep(0.2)
        cls.rpc = rpc
        cls.token = cls.deploy("TokenTestSource")
        cls.nft = cls.deploy("SeatTestSource")

    @classmethod
    def tearDownClass(cls):
        cls.anvil.terminate()
        cls.anvil.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def cast(cls, *args: str) -> str:
        local = args[0] in ("sig-event", "sig")
        cmd = ["cast", *args] if local else ["cast", args[0], "--rpc-url", cls.rpc_url, *args[1:]]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"cast {args[0]} failed: {out.stderr[:400]}")
        return out.stdout.strip()

    @classmethod
    def deploy(cls, name: str) -> str:
        artifact = json.loads((ROOT / "out" / "IndexerSources.sol" / f"{name}.json").read_text())
        out = cls.cast("send", "--private-key", KEY, "--create", artifact["bytecode"]["object"], "--json")
        return json.loads(out)["contractAddress"].lower()

    @classmethod
    def send(cls, to: str, sig: str, *args: str) -> None:
        cls.cast("send", "--private-key", KEY, to, sig, *args)

    @classmethod
    def advance(cls, seconds: int) -> None:
        cls.rpc.call("evm_increaseTime", [seconds])
        cls.rpc.call("evm_mine", [])

    def config(self, **overrides) -> Config:
        env = {
            "CHADBOARD_DB": str(self.tmp / "test.sqlite"),
            "CHADBOARD_RPC_URLS": self.rpc_url,
            "CHADBOARD_CHAIN_ID": "31337",
            "CHADBOARD_TOKEN": self.token,
            "CHADBOARD_BOARD": self.token,  # no board on the test chain: getters return empty words
            "CHADBOARD_SEAT_NFT": self.nft,
            "CHADBOARD_ACTIVATION_EVENT": self.cast("sig-event", "Activated(uint256 indexed seat, address wallet)") + ":seat:1",
            "CHADBOARD_CONFIRMATIONS": "0",
            "CHADBOARD_LOG_CHUNK": "3",
            "CHADBOARD_RETRY_BACKOFF_SECONDS": "0",
            "CHADBOARD_SUPPORT_TARGET": str(1000 * 10**18),
            "CHADBOARD_PUBLICATION_DIR": str(self.tmp / "pub"),
            "CHADBOARD_PORT": str(free_port()),
            "CHADBOARD_RPC_ATTEMPTS": "3",
        }
        env.update(overrides)
        os.environ.update(env)
        return Config()

    def test_pipeline_end_to_end(self):
        t, n = self.token, self.nft
        wei = lambda v: str(v * 10**18)  # noqa: E731
        self.send(t, "mint(address,uint256)", A, wei(1000))
        self.send(t, "mint(address,uint256)", B, wei(500))
        self.send(t, "mint(address,uint256)", C, wei(200))
        for seat, wallet in ((1, A), (2, B), (3, C), (4, D)):
            self.send(n, "mint(uint256,address)", str(seat), wallet)
        for seat, wallet in ((1, A), (2, B), (3, C)):
            self.send(n, "activate(uint256,address)", str(seat), wallet)
        self.advance(10 * DAY)
        self.send(t, "move(address,address,uint256)", B, A, wei(500))  # B drops to zero
        self.send(t, "move(address,address,uint256)", C, B, wei(50))
        self.advance(5 * DAY)
        self.send(t, "move(address,address,uint256)", B, C, wei(50))  # B drops to zero again
        self.advance(3 * DAY)

        cfg = self.config()
        conn = db.connect(cfg.db_path)
        result = refresh_with_retries(conn, cfg)
        self.assertEqual(result["events_added"], 6 + 4 + 3)
        api = Api(conn, cfg)
        snap = api.snapshot("latest")
        self.assertEqual(snap["totalSeats"], 4)
        self.assertEqual(snap["activatedSeats"], 3)
        self.assertEqual(snap["rankedWallets"], 3)
        self.assertTrue(snap["metadata"]["dataQuality"]["transferHistoryComplete"])

        board = api.leaderboard(10, None)
        self.assertEqual([r["wallet"] for r in board["rows"]], [A, C, B])
        a, c, b = board["rows"]
        self.assertEqual(a["balances"]["current"]["raw"], wei(1500))
        self.assertEqual(a["balances"]["balanceVerified"], "verified")
        self.assertTrue(a["holding"]["retainedAllReceived"])
        self.assertTrue(a["holding"]["neverSentAfterFirstAcquisition"])
        self.assertTrue(a["holding"]["heldContinuouslySinceFirstAcquisition"])
        self.assertTrue(a["seat"]["activated"])
        self.assertAlmostEqual(a["holding"]["currentHoldSeconds"] / DAY, 18, delta=0.01)
        self.assertEqual(a["components"]["retention"], 3000)
        self.assertEqual(a["components"]["activatedSeat"], 1000)
        self.assertEqual(a["components"]["balanceSize"], 1500)
        self.assertEqual(a["components"]["neverTransferredOut"], 1500)
        self.assertEqual(a["score"], sum(v for k, v in a["components"].items() if k != "total"))
        self.assertEqual(a["tierName"], "Chad" if a["score"] < 7500 else "GigaChad")

        self.assertEqual(c["balances"]["current"]["raw"], wei(200))
        self.assertEqual(c["balances"]["totalReceived"]["raw"], wei(250))
        self.assertEqual(c["balances"]["totalSent"]["raw"], wei(50))
        self.assertFalse(c["holding"]["retainedAllReceived"])
        self.assertFalse(c["holding"]["neverSentAfterFirstAcquisition"])
        self.assertTrue(c["holding"]["heldContinuouslySinceFirstAcquisition"])
        self.assertEqual(c["holding"]["retentionRatioBps"], 8000)
        self.assertEqual(c["holding"]["soldStatus"], "not-classified")

        self.assertEqual(b["balances"]["current"]["raw"], "0")
        self.assertEqual(b["holding"]["currentHoldSeconds"], 0)
        self.assertAlmostEqual(b["holding"]["longestHoldSeconds"] / DAY, 10, delta=0.01)
        self.assertFalse(b["holding"]["heldContinuouslySinceFirstAcquisition"])

        # Rankings and targeting
        self.assertEqual([r["wallet"] for r in api.ranking("retained-all", 10, None)["rows"]], [A])
        self.assertEqual([r["wallet"] for r in api.ranking("never-sent", 10, None)["rows"]], [A])
        self.assertEqual([r["wallet"] for r in api.ranking("longest-holding", 10, None)["rows"]][:2], [A, C])
        self.assertEqual([r["wallet"] for r in api.ranking("balance", 10, None)["rows"]], [A, C, B])
        targets = api.targets({"activatedOnly": ["1"], "minBalance": ["150"], "heldContinuously": ["1"], "limit": ["5"]}, None)
        self.assertEqual([r["wallet"] for r in targets["rows"]], [A, C])
        self.assertEqual(api.targets({"minRetentionRatio": ["0.9"]}, None)["matched"], 1)
        lookup = api.wallets([A, D], None)
        self.assertTrue(lookup["wallets"][0]["found"])
        self.assertFalse(lookup["wallets"][1]["found"])
        self.assertEqual(lookup["snapshot"]["snapshotId"], snap["snapshotId"])

        # Publication payload in the board's format, with blockers because no board is configured.
        pub = api.publication("latest")
        self.assertEqual(pub["beginEpoch"]["walletCount"], 3)
        self.assertFalse(pub["submittable"])
        self.assertEqual(len(pub["appendWallets"][0]), 3)

        # Idempotent re-run: no duplicate events, a new immutable snapshot, prior one kept.
        again = refresh_with_retries(conn, cfg)
        self.assertEqual(again["events_added"], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM transfer_events").fetchone()[0], 6)
        snaps = api.snapshots()["snapshots"]
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[0]["contentHash"], snaps[1]["contentHash"])
        self.assertEqual(api.leaderboard(10, snaps[1]["snapshotId"])["snapshot"]["snapshotId"], snap["snapshotId"])

        # Re-processing from an older checkpoint still adds nothing (primary key on tx hash + log index).
        db.set_checkpoint(conn, f"transfers:{t}", 1, self.rpc.block(1)["hash"])
        third = refresh_with_retries(conn, cfg)
        self.assertEqual(third["events_added"], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM transfer_events").fetchone()[0], 6)

        # Status shows the last successful refresh and the checkpoint.
        status = api.status()
        self.assertIsNotNone(status["lastSuccessfulRefresh"])
        self.assertEqual(status["transferCheckpoint"]["block"], snap["asOfBlock"])
        self.assertEqual(status["lastRun"]["status"], "success")

        # Retry logic: a bad RPC fails every attempt and records failed runs.
        bad = self.config(CHADBOARD_RPC_URLS="http://127.0.0.1:9", CHADBOARD_RETRY_ATTEMPTS="2", CHADBOARD_RPC_ATTEMPTS="1")
        with self.assertRaises(RuntimeError):
            refresh_with_retries(conn, bad)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'failed'").fetchone()[0], 2)
        self.assertEqual(len(api.snapshots()["snapshots"]), 3)

        # HTTP server: read-only, CORS, routes.
        cfg = self.config()
        server = make_server(conn, cfg)
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://{cfg.host}:{cfg.port}"
            with urllib.request.urlopen(f"{base}/v1/leaderboard?top=50") as resp:
                body = json.loads(resp.read())
                self.assertEqual(resp.headers["access-control-allow-origin"], "*")
                self.assertEqual(len(body["rows"]), 3)
            with urllib.request.urlopen(f"{base}/v1/site-feed") as resp:
                feed = json.loads(resp.read())
                self.assertEqual(feed["wallets"], 3)
                self.assertFalse(feed["stale"])
            with urllib.request.urlopen(f"{base}/v1/wallets?addresses={A},{C}") as resp:
                self.assertEqual(len(json.loads(resp.read())["wallets"]), 2)
            req = urllib.request.Request(f"{base}/v1/status", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 405)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base}/v1/leaderboard?top=7")
            self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
