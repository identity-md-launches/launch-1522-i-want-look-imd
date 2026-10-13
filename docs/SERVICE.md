# ChadBoard data service

`service/` holds the daily data pipeline and the read-only query API for
ChadBoard. It is a standard-library Python 3.10+ program with a single-writer
SQLite database: no third-party packages, no signing keys, no write endpoints.

```
service/chadboard/
  config.py     environment-driven settings (addresses from the pinned records)
  rpc.py        JSON-RPC client: endpoint rotation, retries, adaptive log ranges
  db.py         SQLite schema: raw events, checkpoints, runs, immutable snapshots
  indexer.py    chunked, checkpointed, idempotent log indexing (IMD + seat NFT)
  snapshot.py   wallet metrics, ChadBoard holding score, snapshot storage
  pipeline.py   refresh orchestration with retries; board-format publication
  radar.py      optional structured Radar cache and source conflict reconciliation
  backfill.py   archive preflight, dry-run, request estimate and range coverage
  api.py        GET-only JSON API with CORS
  __main__.py   CLI: refresh | serve | run | status | export | preflight | coverage | radar
service/tests/test_pipeline.py   end-to-end test on a loopback Anvil chain
```

See [RADAR.md](RADAR.md) for optional enrichment, source fields, archive routing,
quarantine/caching behavior and the distinction between service holding scores and
published ChadBoard scores. The current worker did not complete the full mainnet
backfill; see [validation](VALIDATION.md).

## Run it on the worker / VPS

```sh
export PYTHONPATH=service
export CHADBOARD_DB=/var/lib/chadboard/chadboard.sqlite      # durable disk
# Supply ETH_ARCHIVE_RPC_URL privately in the server environment.
# Keep CHADBOARD_RPC_URLS for public current-state reads.
python3 -m chadboard refresh      # one indexing + snapshot pass (resumable)
python3 -m chadboard run          # API on 127.0.0.1:8787 + refresh every 24 h
python3 -m chadboard status       # JSON: last successful refresh, checkpoint, latest snapshot
```

`run` refreshes immediately when the last success is older than
`CHADBOARD_INTERVAL_SECONDS` (default 86400) and then once per interval. A
failed refresh is retried `CHADBOARD_RETRY_ATTEMPTS` times with linear
backoff, every attempt is recorded in the `runs` table, and the previous
snapshot keeps serving. Put `run` under systemd (`Restart=always`) and a
reverse proxy with TLS in front of the port; the API needs no authentication
because it is read-only and holds no secrets.

The full IMD transfer backfill (token deployed at block 23501863, tens of
thousands of transfers) needs an RPC that serves historical `eth_getLogs`.
The two public endpoints in `network.json` refuse ranges older than a few
thousand blocks, so supply `ETH_ARCHIVE_RPC_URL` and run the archive preflight
first. Provider plan limits also matter: see `RADAR-VALIDATION.json`. Each chunk commits its events and checkpoint in one transaction, so a
killed process resumes exactly where it stopped; `CHADBOARD_MAX_BLOCKS_PER_RUN`
bounds one pass and still yields a consistent snapshot as of the last fully
indexed block, flagged `transferHistoryComplete=false` until the backfill
catches up and origin/range coverage is verified. API read transactions use their
own connections so partial writes cannot leak into an in-flight response.

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHADBOARD_DB` | `service/data/chadboard.sqlite` | SQLite file (WAL mode) |
| `CHADBOARD_RPC_URLS` | the two `network.json` RPCs | comma-separated, rotated on failure |
| `CHADBOARD_TOKEN` | IMD from `network.json` | ERC-20 to index |
| `CHADBOARD_BOARD` | IMDChadBoard from `deployment.json` | board whose configuration is read |
| `CHADBOARD_SEAT_NFT` | empty | seat NFT when the board's `seatNFT()` is still unset |
| `CHADBOARD_ACTIVATION_EVENT` | empty | `<topic0>:<walletTopic>` or `<topic0>:seat:<seatTopic>` |
| `CHADBOARD_CONFIRMATIONS` | 64 | observation depth; never past the `finalized` tag |
| `CHADBOARD_LOG_CHUNK` | 2000 | initial `eth_getLogs` range, halves on range errors |
| `CHADBOARD_MAX_BLOCKS_PER_RUN` | 0 (unbounded) | bound one backfill pass |
| `CHADBOARD_INTERVAL_SECONDS` | 86400 | refresh period for `run` |
| `CHADBOARD_RETRY_ATTEMPTS` / `_BACKOFF_SECONDS` | 4 / 30 | refresh retries |
| `CHADBOARD_RPC_ATTEMPTS` / `_TIMEOUT` | 5 / 60 | per-request retries and timeout |
| `CHADBOARD_SUPPORT_TARGET` | 10,000 IMD (wei) | balance that earns the full balance-size component |
| `CHADBOARD_VERIFY_BALANCES` | 100 | top-N wallets checked with `balanceOf` at the as-of block |
| `CHADBOARD_HOST` / `CHADBOARD_PORT` | 127.0.0.1 / 8787 | API bind address |
| `CHADBOARD_PUBLICATION_DIR` | `service/data/publications` | board-format payloads |

## What a refresh does

1. Checks the RPC chain id, picks the as-of block (head minus confirmations,
   capped by `finalized`), and reads the board's `seatNFT`, `reporter`,
   `latestEpoch` and `configuration` at that block.
2. Indexes IMD `Transfer` logs from the token's deployment block (found by
   binary search over `eth_getCode` on first run) to the as-of block. Each
   event is keyed by `(tx_hash, log_index)` with `INSERT OR IGNORE`; a
   checkpoint stores the last indexed block and its hash. On start the
   checkpoint hash is re-read from the chain; a mismatch rewinds 256 blocks
   and re-indexes (reorg protection on top of finality).
3. Indexes the seat NFT's ERC-721 `Transfer` logs and, when configured, the
   activation event, the same way.
4. Replays all transfers in canonical order to derive, per wallet: balance,
   total received and sent, transfer counts, first acquisition, the start of
   the current nonzero-balance streak, every closed streak, whether any
   outgoing transfer happened after the first acquisition, and the last
   outgoing time. Exact block timestamps are fetched for the blocks that matter
   and cached in the `blocks` table.
5. Verifies the top-N derived balances against `balanceOf` at the as-of block
   and marks each as `verified`, `derived-only` or `mismatch`.
6. Scores and ranks the wallet universe, stores the snapshot and its rows in
   one transaction, and writes the board-format publication payload.

### Wallet universe and seat status

| Board / settings | Universe | `seat.status` |
| --- | --- | --- |
| seat NFT and activation event known | wallets owning at least one activated seat | `activated` |
| seat NFT known, activation event unset | every current seat owner | `holder` (activation unverified) |
| seat NFT unknown (today's live state) | every wallet with a nonzero indexed IMD balance | `unknown` |

The live board has `seatNFT = 0x0`, `reporter = 0x0` and configuration
revision 0 (read at block 26184378 on 2026-10-13), and the seat NFT address
is not in the pinned records, so the service never hard-codes one. Once the
owner calls `setSources`, the service picks the address up from the board on
its next refresh; the activation event signature still has to be supplied
through `CHADBOARD_ACTIVATION_EVENT` because the contract does not store it.
Every response carries `dataQuality` describing exactly which of these
situations applies.

### ChadBoard holding score (`chadboard-holding-v1`)

| Component | Max | Rule |
| --- | ---: | --- |
| retention | 3000 | `3000 × min(balance, received) / received` |
| currentHolding | 2000 | `2000 × min(current streak, 365 d) / 365 d` |
| longestHolding | 1000 | `1000 × min(longest streak, 365 d) / 365 d` |
| neverTransferredOut | 1500 | no outgoing transfer after the first acquisition |
| balanceSize | 1500 | `1500 × min(balance, supportTarget) / supportTarget` |
| activatedSeat | 1000 | `seat.status == activated` |

Tiers: Observer 0–2499, Contributor 2500–4999, Chad 5000–7499, GigaChad
7500–10000. Ordering is score descending, then numeric wallet address
ascending, so ranks are unique and deterministic. This is a holding and
retention heuristic computed from transfer history; it is not the on-chain
score of `IMDChadBoard`, which additionally needs launch, claim, purchase
and app sources that only the owner can configure.

### Precise holding definitions

- `currentHoldSeconds`: as-of time minus the moment the balance last went from
  zero to positive (0 when the balance is zero).
- `longestHoldSeconds`: the longest nonzero-balance streak, closed or current.
- `heldContinuouslySinceFirstAcquisition`: balance positive and never zero
  since the first incoming transfer.
- `retainedAllReceived`: `balance == totalReceived`.
- `neverSentAfterFirstAcquisition`: no outgoing transfer at or after the first
  incoming transfer in the indexed history. Both fields are returned; they are
  different claims.
- `soldStatus` is always `not-classified`: an outgoing transfer is a transfer,
  never inferred to be a sale.
- `balanceVerified` and `dataQuality.transferHistoryComplete` mark derived or
  partial data explicitly.

## Query API

All routes are `GET`, return JSON, send `Access-Control-Allow-Origin: *`, and
accept `?snapshot=<id>` to read any prior immutable snapshot. Every result
carries `snapshot.snapshotId` and `snapshot.asOfBlock`.

| Route | Purpose |
| --- | --- |
| `/v1/status` | last successful refresh (unix + ISO), last run, checkpoint, latest snapshot |
| `/v1/snapshots` | every stored snapshot, newest first |
| `/v1/snapshot/latest`, `/v1/snapshot/<id>` | snapshot header and metadata |
| `/v1/wallets?addresses=0x..,0x..` | up to 100 wallets: score, tier, seat, balances, holding history |
| `/v1/leaderboard?top=10|50|100|1000[&offset=N]` | ranked wallets |
| `/v1/rankings/current-holding` | longest current continuous holding |
| `/v1/rankings/longest-holding` | longest historical holding |
| `/v1/rankings/balance` | highest current balance |
| `/v1/rankings/retained-all` | balance equals total received |
| `/v1/rankings/retention-ratio` | highest balance / received |
| `/v1/rankings/never-sent` | no outgoing transfer after first acquisition |
| `/v1/targets?...` | airdrop filters: `activatedOnly`, `minScore`, `tier`, `minHoldDays` or `minHoldSeconds`, `minBalance` (IMD), `minRetentionRatio`, `neverSent`, `retainedAll`, `heldContinuously`, `limit` |
| `/v1/publication/latest` | board-format payload for the reporter |
| `/v1/site-feed` | compact feed the static website reads |

Example:

```sh
curl "http://127.0.0.1:8787/v1/targets?activatedOnly=1&minScore=5000&minHoldDays=90&minRetentionRatio=0.9&limit=500"
```

## Publishing to the deployed board and website

`write_publication` emits `beginEpoch` (SnapshotInput with the snapshot's
block, hash, timestamp, census and SHA-256 content hash as `evidenceHash`),
`appendWallets` batches of 20 `WalletReport` rows and `finalizeEpoch`, in the
exact struct layout of `src/IMDChadBoard.sol`. Launch, claim, purchase and app
metrics are zero until the owner configures those sources, and the payload
lists the blockers that make it non-submittable today (reporter, seat NFT and
token policies unset). The reporter signs with their own tooling; the service
stores no key.

The static site reads the service when the board has no epoch: build with
`VITE_CHADBOARD_API=https://<service-host> npm run build`, or open the published
site with `#api=https://<service-host>` once (remembered in `localStorage`;
`#api=` clears it). It then shows the snapshot id, census, ranked count and
observation block and serves wallet and leaderboard queries from the snapshot.
Once an on-chain epoch exists the contract wins and the feed is ignored.

## Tests

```sh
python3 -m unittest discover -s service/tests -v
```

The end-to-end test deploys the fixture token and seat sources on a loopback
Anvil, emits mints, activations and transfers across simulated days, runs the
refresh, and checks: ranking order and tie-breaking, every holding field,
score components, balance verification, rankings and target filters, wallet
lookup for a ranked and an absent wallet, the publication payload and its
blockers, idempotent re-runs (zero new events, prior snapshot retained,
identical content hash), re-processing from an older checkpoint without
duplicates, failed-run recording and retries against a dead RPC, and the HTTP
server (CORS, 405 on writes, 400 on a bad `top`).
