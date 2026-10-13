"""Command line entry point: `python3 -m chadboard <refresh|serve|run|status|export>`."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time

from . import db
from .api import Api, make_server
from .config import Config
from .pipeline import refresh_with_retries


def scheduler_loop(conn, cfg: Config, stop: threading.Event) -> None:
    """Refresh on start when the last success is older than the interval, then every interval."""
    while not stop.is_set():
        last = db.last_successful_run(conn)
        due_at = (last["finished_at"] + cfg.interval_seconds) if last else 0
        wait = max(0, due_at - time.time())
        if wait > 0:
            logging.getLogger("chadboard.scheduler").info("next refresh in %d s", int(wait))
            if stop.wait(wait):
                return
        try:
            refresh_with_retries(conn, cfg)
        except Exception as err:  # noqa: BLE001 - keep serving the last good snapshot and try again later
            logging.getLogger("chadboard.scheduler").error("refresh failed; retrying next interval: %s", err)
            if stop.wait(cfg.interval_seconds):
                return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chadboard", description="ChadBoard IMD data service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="index to the finalized block, store a snapshot and the publication payload")
    sub.add_parser("serve", help="serve the read-only query API")
    sub.add_parser("run", help="serve the API and refresh on the configured interval")
    sub.add_parser("status", help="print the service status as JSON")
    plan = sub.add_parser("preflight", help="verify archive history, estimate requests and run a small isolated dry-run")
    plan.add_argument("--end-block", type=int)
    sub.add_parser("coverage", help="report exact indexed block coverage and gaps")
    sub.add_parser("radar", help="refresh optional Radar cache independently of Ethereum")
    export = sub.add_parser("export", help="print a snapshot's full ranked table as JSON")
    export.add_argument("--snapshot", default="latest")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    cfg = Config()
    if args.command == "preflight":
        from .backfill import preflight
        print(json.dumps(preflight(cfg, args.end_block), indent=2))
        return 0
    conn = db.connect(cfg.db_path)
    api = Api(conn, cfg)

    if args.command == "coverage":
        from .backfill import coverage
        print(json.dumps(coverage(conn, cfg), indent=2))
        return 0
    if args.command == "radar":
        from .radar import Radar
        print(json.dumps(Radar(conn, cfg).refresh(), indent=2))
        return 0

    if args.command == "refresh":
        result = refresh_with_retries(conn, cfg)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(api.status(), indent=2))
        return 0
    if args.command == "export":
        snap = api.snapshot(args.snapshot)
        rows = conn.execute("SELECT * FROM snapshot_wallets WHERE snapshot_id = ? ORDER BY rank", (snap["snapshotId"],)).fetchall()
        from .api import wallet_json

        print(json.dumps({"snapshot": snap, "wallets": [wallet_json(r) for r in rows]}, indent=2))
        return 0

    stop = threading.Event()
    server = make_server(conn, cfg)
    threads = [threading.Thread(target=server.serve_forever, name="api", daemon=True)]
    if args.command == "run":
        threads.append(threading.Thread(target=scheduler_loop, args=(conn, cfg, stop), name="scheduler", daemon=True))
    for t in threads:
        t.start()
    logging.getLogger("chadboard").info("API listening on http://%s:%d/v1", cfg.host, cfg.port)

    def shutdown(*_):
        stop.set()
        server.shutdown()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while any(t.is_alive() for t in threads[:1]):
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
