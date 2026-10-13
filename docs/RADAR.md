# Optional IMD Radar enrichment

Radar augments Ethereum evidence. It cannot populate `snapshot_wallets`, choose
ranked wallets, change scores or ordering, modify the IMD ledger, or classify a
transfer as a sale. `snapshot.py` has no Radar dependency. A Radar-only wallet is
an unranked bootstrap candidate, even when Radar reports substantial rewards.

The existing service's `chadboard-holding-v1` score is an Ethereum transfer and
holding heuristic. It is **not** the deployed contract's participation score.
The website labels these separately and always prefers a published contract
epoch. The board still needs its owner's seat, reporter and policy configuration;
Radar does not substitute for those settings or on-chain publication.

## Enable and operate

Python 3.10+ standard library only; no new package dependencies. From the root:

```sh
export PYTHONPATH=service
export CHADBOARD_DB=/tmp/chadboard-local.sqlite
export CHADBOARD_RADAR_ENABLED=1
python3 -m chadboard radar       # cache enrichment, no Ethereum indexing
python3 -m chadboard serve       # read-only API, default 127.0.0.1:8787
```

Use a durable database path in production. `run` combines the API with the
existing daily Ethereum refresh. That refresh commits its ranking before fetching
Radar. Radar fetch errors do not mark Ethereum indexing as failed. The API uses
independent SQLite read transactions so uncommitted updates cannot become visible.
`radar` is also useful for bootstrapping before a complete Ethereum backfill exists.
No endpoint starts network work: API reads consume the cache only.

| Setting | Default | Meaning |
| --- | ---: | --- |
| `CHADBOARD_RADAR_ENABLED` | `0` | Explicit opt-in; `1` enables refreshes |
| `CHADBOARD_RADAR_TTL_SECONDS` | `900` | Avoid repeat fetches, including failed requests, within this interval |
| `CHADBOARD_RADAR_MAX_AGE_SECONDS` | `86400` | Staleness threshold for both retrieval age and source update age |
| `CHADBOARD_RADAR_TIMEOUT` | `8` | Timeout per HTTP request |
| `CHADBOARD_RADAR_BUDGET_SECONDS` | `60` | Stop scheduling new fetch groups after this duration; an in-flight group may finish afterward |
| `CHADBOARD_RADAR_SEAT_LIMIT` | `2048` | Maximum detail requests per pass; rotates across known seats |
| `CHADBOARD_RADAR_MIN_LIQUIDITY_USD` | `2000` | Local minimum; the larger of this and Radar's minimum is used |

Requests run in groups of at most four. A failed swarm request skips detail
fetches; four consecutive detail failures stop the batch. A deadline or configured
limit can leave partial detail coverage. Missing status is `null`, never inferred
from the compact flags. Retry on a later pass; status and per-result quality expose
missing or stale data. A working Ethereum API and site do not require Radar.

In the static website, expand **Data sources · Ethereum rankings**, then **Connect
a data service**. Supply your service's HTTPS URL (localhost HTTP is supported).
The URL is remembered locally; **Disconnect service** clears the runtime setting.
Alternatively retain the existing `#api=https://…` or `VITE_CHADBOARD_API` setting.
The private archive RPC must never be used as this URL or any `VITE_` variable.

## Structured source contracts

The adapter uses only:

- `https://www.imdradar.site/api/feed?view=swarm`
- `https://www.imdradar.site/api/feed?view=seat&id={seat}`
- `https://www.imdradar.site/api/launchpad?view=agents`

No HTML scraping or inferred NFT address is involved. Observed source shapes were
checked on 2026-10-13 UTC. Radar does not publish a schema marker in these responses;
`imd-radar-observed-2026-10/v1` identifies this decoder, not a claimed upstream
schema guarantee. Unknown shape/type changes are quarantined as malformed.

| Input | Imported fields / interpretation |
| --- | --- |
| Swarm `seats` tuple, exactly 11 fields | seat, agent ID, attempts, accepted, rejected, failed, pending, latest-work milliseconds, two **uninterpreted** flags, owner wallet |
| Seat detail object | seat, agent ID, owner, explicit `online` and `status`, work counts and work records; latest work is the maximum work timestamp |
| Swarm activity | raw job/event metadata, running jobs, health and counts; upstream descriptions are inert data |
| Launch agents | wallet, seats, accepted tasks, reported participation count and per-launch participation, reported reward/unclaimed USD totals |
| Launch token tuple, exactly 3 fields | launch number, approximate token reward amount, claimed flag (`0` or `1`); interpretation cross-checked against upstream reported totals |
| Launch definitions | number, symbol, price, liquidity, `counted` eligibility flag |

The reward tuple does not supply a token contract address, claim transaction,
claim timestamp or exact raw ERC-20 units. None is invented. A claimed flag is a
Radar observation, not proof of a claim, sale or continued ownership. API prices
and rounded amounts are approximate estimates; Decimal arithmetic avoids adding
extra floating-point rounding to the calculations.

A launch enters the eligible reward list/value estimate only when `counted` is
true, its liquidity meets **both** minima, and its price is positive. Unknown
launches and low/unverified-liquidity launches remain in participation and in the
raw response but are excluded from `rewards`, `eligibleValueUsd` and
`eligibleUnclaimedUsd`. `reportedValueUsd` / `reportedUnclaimedUsd` preserve Radar's
own totals under separate names. No reward estimate enters ranking calculations.

## Persistence and immutable evidence

`radar_responses` keeps the exact HTTP body bytes, fixed public `source_url`, Unix
retrieval time, SHA-256 of those bytes, schema marker, validation result, and a
normalized JSON observation. Malformed JSON bodies are retained with `valid=0`.
Network failures record an attempt/error; they do not manufacture a response.

`radar_cache` points to the last valid response for each URL. A malformed response
or unavailable service never replaces that pointer. `snapshot_radar` binds
response IDs once when an Ethereum snapshot is created. Refreshing the cache
cannot change historical enrichment, ranking rows or the ranking content hash.
Staleness is evaluated at read time, so a saved response can later become stale
without mutating it. The ranking evidence hash deliberately excludes Radar.

`snapshot_seats` freezes Ethereum ownership and configured activation evidence at
the snapshot block. Raw `seat_events` and `transfer_events` remain separate.
Repeated identical seat/wallet/response relationships are deduplicated and flagged.
One wallet holding several different seats is legitimate. Multiple reported owners
of the same seat are preserved and flagged, including disagreements between swarm,
seat detail and launch records. Ethereum/Radar ownership or activation disagreements
include both values and `preferredSource: ethereum`. Different observation times
and agent-status versus activation semantics are disclosed. No field is silently
replaced. An unknown Ethereum seat source remains unknown.

Back up the SQLite database using SQLite's backup API or a consistent stopped
copy (include WAL state when applicable). Responses referenced by snapshots must
be retained; this version does not automatically prune evidence. Live cache and
ledger databases belong on server storage, not in the static export or Git bundle.

## API additions

| GET route | Result |
| --- | --- |
| `/v1/radar/status` | enablement, cached response count, stale count, failures, detail count and configured limit |
| `/v1/radar/seats?seat=0` | cached observations for one seat, both owners when available, launch participation and source evidence |
| `/v1/radar/wallets?wallet=0x…` | wallet-to-seat bootstrap relationships; does not create a ranked wallet |
| `/v1/radar/activity` | swarm events, running jobs and activity metadata |
| `/v1/radar/raw/<responseId>` | original body as base64 plus URL, retrieval time, hash, schema and validation result |

Seat and wallet routes accept `?snapshot=<id>` for frozen enrichment; otherwise
they use the latest valid cache and cross-check the latest stored Ethereum seat
map. The two clocks are explicit (`asOfBlock: null` for Radar,
`ethereumAsOfBlock` and per-relationship block for Ethereum).

Existing wallet, leaderboard, ranking and targeting routes add `source`
(`ethereum`, `imd-radar`, or `merged`), `sourceRetrievedAt` (Unix seconds),
`asOfBlock`, `dataQuality`, `conflict` and `conflicts`. Wallet rows contain a
separate `radar` object, plus `fieldSources` naming Ethereum for rank, score,
seat, balance and holding accounting. Each raw Radar source retains its own
retrieval/update times and hash; the merged row's timestamp describes its Ethereum
snapshot creation/retrieval, not a claim that all sources were simultaneous.
The compact site feed now uses `source: ethereum`, `provider: chadboard-data`.
The browser's internal `source: service` discriminator is a transport choice,
not a data-authority claim. JSON downloads preserve enrichment; CSV adds source,
time, block and conflict columns.

## Historical Ethereum preflight

Configure `ETH_ARCHIVE_RPC_URL` in the **server process environment**. Its value
is never logged, serialized into configuration/API metadata, included in a report,
or passed into Vite. RPC errors expose diagnostic categories and numeric range
caps, never provider URLs or echoed bodies. `CHADBOARD_RPC_URLS` remains the public
current-read list. `HistoricalRpc` routes older block/state requests and deep log
scans to the archive provider; browser/current reads use the public RPCs.

```sh
# ETH_ARCHIVE_RPC_URL must already be supplied privately by the server environment.
PYTHONPATH=service python3 -m chadboard preflight
# Inspect the estimate before a full run; a bound makes incremental progress safe.
CHADBOARD_MAX_BLOCKS_PER_RUN=10000 PYTHONPATH=service python3 -m chadboard refresh
PYTHONPATH=service python3 -m chadboard coverage
```

A fresh mainnet IMD refresh runs preflight automatically before its first index
mutation and stores the sanitized plan in SQLite. Already-checkpointed incremental
refreshes do not repeat it. Run the standalone command first to inspect the cost.

Preflight verifies the variable, chain, token deployment via historical code,
old block availability, separated Transfer-log windows across the intended range,
a small real-indexer dry-run, and an idempotent resume. It reports effective range
limits, requests and measured sequential duration. It does not equate samples with
complete coverage. Adaptive log scans learn numeric provider caps and do not keep
retrying a known oversized range.

Every completed range writes logs, its range record and block/hash checkpoint in
one SQLite transaction. Resume validates the checkpoint hash, rewinds a bounded
reorg, and deduplicates by transaction/log index. Coverage reports exact origin,
checkpoint/end, unique transfer counterparties, event count and uncovered ranges.
An explicit late start or unverified legacy database cannot claim complete history.
Snapshots from incomplete backfills are provisional; the static feed pauses paid
queries. Board configuration is reread at the actual snapshot block after a bounded
pass. No live publication transaction is sent by this service.

Actual worker capability/coverage, including the provider's 10-block plan limit,
is recorded in `docs/RADAR-VALIDATION.json` and `docs/VALIDATION.md`.
Whole-history wallet and event totals remain unknown until the backfill completes.
