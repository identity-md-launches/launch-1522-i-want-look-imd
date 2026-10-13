# Radar adapter validation

Worker checks on 2026-10-13 UTC (2026-10-14 Asia/Taipei). This is a record of local
verification, not independent certification. The existing site was extended;
contracts, deployment addresses, dependencies and build configuration were retained.

## Outcome and limits

The optional adapter, source/conflict APIs, responsive source lookup, tests,
source, unchanged npm lockfile, and production `dist/` are delivered. No contract
was deployed, no real transaction was signed, and no site publication command ran.

**Full historical mainnet backfill is incomplete.** The supplied archive endpoint
responded: “Under the Free tier plan, you can make eth_getLogs requests with up to
a 10 block range.” Both public endpoints returned HTTP 403 for the tested deep
historical query. A 10-block range works. The measured sequential full-scan estimate
is **536,557 RPC requests / 81,840 seconds (22.7 hours)** before additional timestamp
and balance checks. That exceeds this worker's bounded runtime. The full scan was
not started and the samples were not promoted to a complete ranking snapshot.

**WebKit interaction validation is unperformed.** Playwright WebKit 27.2/build 2370
was downloaded outside the repository. Missing runtime libraries were unpacked
under `/tmp/`; an actual `ctypes` load verified GLES availability. The launcher
needed its inherited library path preserved. After supplying libraries and
GSettings schemas, the browser still closed on `newPage`; debug output included
“No GSettings schemas are installed on the system” on an earlier attempt and
“Could not create EGL display: no supported platform available.” The final attempt
with software-rendering options still returned `Target page, context or browser
has been closed`. No successful WebKit result is claimed for this revision.

The deployed board still has no published epoch, so the live site truthfully
pauses paid queries until eligible data exists. The existing service holding score
is labeled separately from the contract's participation score. The owner-settable
seat/activation/reporting configuration is not replaced with Radar guesses.

## Requirements and implementation

| Requirement | Implemented / checked |
| --- | --- |
| Structured Radar endpoints, optional dependency | Only the three specified API URLs; disabled by default; no HTML scraping or browser-to-Radar dependency |
| Seat/agent/owner/status/work/latest timestamp | Swarm summary plus explicit seat details, persisted with per-source provenance; unknown compact status flags stay uninterpreted |
| Wallet relationships, launch participation and rewards | Separate observations; low/unverified-liquidity rewards excluded from eligible estimates while raw data and participation remain |
| Raw response provenance | Exact bytes, source URL, retrieval timestamp, SHA-256, decoder schema version, validation state; raw API returns base64 |
| Bootstrap/cross-check | Unranked wallet/seat lookup; immutable Ethereum seat map; source and duplicate conflicts preserve both values |
| Ethereum ranking authority | Ranking derivation never imports Radar; raw observations bind after the Ethereum snapshot commits; score/rank/accounting fields remain Ethereum sourced |
| No Radar balance/sale/retention authority | Independent fields and tests; reported rewards/claimed flags are explicitly estimates, never transfer classifications |
| Immutable snapshots | Frozen response IDs and seat ownership; refresh tests preserve content hash and previous observations; API readers have independent transactions |
| Source fields | Data responses identify source, retrieval time, block where applicable, data quality and conflict details; Radar has no invented Ethereum block |
| Outage, malformed, stale, disagreement, duplicates, liquidity tests | All six requested cases pass in the deterministic Python suite |
| Site/first mobile screen | Existing query preserved; 390×844 shows product, wallet field, fee and primary action; source disclosure follows snapshot summary |
| Static export and metadata | Relative Vite assets, title, favicon, description, og:title, local og:image; no credential/backend in export |
| Documentation | README install/preview/rebuild, DESIGN.md final tokens/components, docs/RADAR.md operations/API/semantics, exact archive report |

## Executed checks

Dependencies were installed using the existing `web/package.json` and
`web/package-lock.json` in `/tmp/chadboard-build/web`. No repository
`node_modules`, manifest/lockfile edit, ignore rule, registry mirror or dependency
archive was added. The finished export was copied back to root `dist/`, with old
hashed assets removed.

| Actual command / check | Result |
| --- | --- |
| `npm ci --prefix /tmp/chadboard-build/web --cache /tmp/chadboard-npm-cache --no-audit --no-fund` | Exit 0; 86 packages installed using unchanged lockfile |
| `npm run typecheck --prefix /tmp/chadboard-build/web` | Exit 0; strict `tsc --noEmit` |
| `npm test --prefix /tmp/chadboard-build/web` | Exit 0; 10/10 tests, including pinned ABI hash and malformed/source URL validation |
| `npm run build --prefix /tmp/chadboard-build/web` | Exit 0; Vite 7.1.12, 1,100 modules, relative production assets |
| `PYTHONPYCACHEPREFIX=/tmp/chadboard-pycache python3 -m unittest discover -s service/tests -v` | Exit 0; 19/19 tests, including local Anvil integration, checkpoint replay, API, all Radar cases, pipeline failure isolation, required first-scan preflight and range-cap learning |
| `tsx scripts/check-browser.ts` against final root `dist/` | Chromium: 18 grouped checks pass; primary wallet/leaderboard flows, payment mock/recovery, filters/downloads, source lookup/conflicts/stale/exclusions/malformed/outage handling and service score distinction |
| Axe via `@axe-core/playwright` | Zero violations on empty view, payment review, wallet results and expanded Radar fixture states in Chromium |
| `node .imd/reads/skills/design-critic/scripts/taste.mjs --out test/scratch/taste` | 16/16 checks pass with external Playwright module configured |
| Browser MCP production inspection | Successful local `/preview/` navigation; inspected actual 390 and 1440 screenshots, keyboard/form source lookup with live cached Radar data; no horizontal overflow in inspected viewports |
| Live Radar structured API cache | 1,079 swarm seats, 526 reward wallets, 3,174 eligible and 45,426 excluded reward entries; 95 seat details cached in bounded follow-up, 16 failed detail requests explicitly reported |
| Archive preflight and dry-run | Chain 1, historical code/block verified, separated Transfer windows succeed, real-indexer dry-run + resume succeed; full coverage remains incomplete |

The live cache-only API intentionally returned HTTP 404 for `/v1/site-feed`
because no Ethereum snapshot had been indexed in that smoke database. The browser
logged that expected response, kept the honest empty-board state and successfully
loaded Radar status/seat observations (HTTP 200). It did not crash or request a
payment. Earlier expired local preview sessions were restarted for final inspection.

The Python integration suite uses public **local Anvil test keys** only. Mock
leaderboards, rewards, conflicts, wallet signing and receipts in the browser
harness are fixtures, are labeled in their report, and are not bundled into the
production UI. The live Radar smoke cache/ledger fixtures remain under disposable
`test/scratch/`; no test data is published as live rankings.

The Chromium harness was run from the isolated web copy with:

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/chadboard-browsers \
IMD_PLAYWRIGHT=/tmp/chadboard-test-tools/node_modules/playwright/index.mjs \
IMD_AXE=/tmp/chadboard-test-tools/node_modules/@axe-core/playwright/dist/index.mjs \
IMD_EXPORT=<repository>/dist \
IMD_BROWSER_OUTPUT=<repository>/test/scratch/chromium \
  ./node_modules/.bin/tsx scripts/check-browser.ts
```

The taste probe used the same `PLAYWRIGHT_BROWSERS_PATH` and `IMD_PLAYWRIGHT`.
Its original missing-Playwright attempt was repaired by installing the tooling
outside the repository. Bounded foreground preview servers were used for MCP
inspection; they are not a hosting deliverable. The obsolete original website
validation report is retained as historical documentation, not this run's evidence.

## Exact Ethereum scope

See [RADAR-VALIDATION.json](RADAR-VALIDATION.json) (the `archivePreflight` object) for the machine-readable
report, timestamps, hash and per-window request evidence.

| Item | Actual value |
| --- | --- |
| Historical start | **23,501,863** (first IMD code, verified by binary search) |
| Intended historical end | **26,184,642** (frozen target for this check) |
| Deployment block hash | `0xcdf1f64305570e93a9380bd0f484e5e17da3a54a1f346d8b8f46d34031b67284` |
| Dry-run range | 23,501,863–23,501,882 |
| Dry-run events / resume additions | 0 / 0; checkpointed indexer executed successfully |
| Transfer probes | 23,501,863–23,501,872; 24,172,557–24,172,566; 24,843,252–24,843,261; 25,513,947–25,513,956; 26,184,633–26,184,642 |
| Observed events / unique counterparties | **8 / 11**, only in the probed windows; zero address excluded; addresses may include contracts |
| Whole-history wallet/event counts | **Unknown**, not asserted from samples |
| Uncovered ranges | **23,501,883–24,172,556; 24,172,567–24,843,251; 24,843,262–25,513,946; 25,513,957–26,184,632** |

The worker shell initially did not inherit `ETH_ARCHIVE_RPC_URL`. The value
already supplied in the assignment was set only in server-process memory for
these checks, never written to a repository file or passed to the frontend.
Historical state and deep event calls used that private endpoint; routine website
reads remained on the public endpoints. The initial oversized-range preflight was
stopped after learning the provider's plan cap. The adaptive client now learns
that cap without repeated oversized retries.

## Better Interface: six-domain review

Applied the pinned guide while building; preserved the existing paper/ink/violet
query UI. The product's visual idea remains a compact record of wallet activity,
with source evidence disclosed beneath the main query instead of competing with it.

| Domain | Coverage and evidence | Limits |
| --- | --- | --- |
| Accessibility | Checked native buttons/labels/details, focused invalid lookup, live status, dialog focus/recovery, keyboard pack selection, reduced motion; Axe on four states | No screen-reader session, physical device or full WCAG certification |
| Layout | Checked 320, 390, 820, 1440 widths in harness; main action at y=715–763 within 390×844; query panel ends at y=817.4; source/conflict strings wrap | 200% root text enlargement tested, not native browser zoom; no RTL/localization requirement |
| Writing | Checked source labels, “Sources disagree”, both owners, recoverable errors, unclaimed/claimed caveats, stale/partial states and service-vs-contract score distinction | Radar's external work descriptions are preserved data, not authored UI copy |
| Typography | Checked existing six-step scale, Arial/system stack, 400/600/700 weights, selectable full addresses/hashes and 16px inputs; probe within size/family limits | OS font rendering and physical iOS input zoom unverified |
| Colors | Checked semantic token reuse and redundant text cues; probe says every measured text pair meets 4.5:1 (3:1 large), Axe reports no contrast violations in expanded source fixture | No invented contrast ratios; no alternate theme exists |
| UI | Checked independent source loading/empty/error/retry, no new animation, native disclosure, 48px controls, flat borders and source evidence links | WebKit could not start a usable page; no native Safari claim |

## Findings, fixes and rechecks

| Finding | Source location | Correction and evidence |
| --- | --- | --- |
| High: RPC error messages could expose provider URLs/echoed credentials | `service/chadboard/rpc.py:26` | Category-only diagnostics and numeric caps; secret-redaction test passes; candidate-file credential scan recorded below |
| High: a bounded backfill could appear complete merely because its snapshot used the checkpoint block | `service/chadboard/snapshot.py:267`, `service/chadboard/indexer.py:35` | Origin verification, indexed ranges and target coverage now gate completeness; provisional feed prevents payment; integration/checkpoint tests pass |
| High: optional source failure must not roll back a valid ranking | `service/chadboard/pipeline.py:87`, `service/chadboard/radar.py:200` | Commit Ethereum first, keep last valid Radar cache, bounded requests/circuit breaker; outage and unexpected-exception tests pass |
| Medium: service score could be mistaken for the contract's published participation score | `web/src/App.tsx:607`, `web/src/Results.tsx:286` | Contextual score labels/method, unknown seat census shown as unavailable; no fabricated reporter/method hash; Chromium service-feed interaction checks pass |
| Medium: compact seat flags have undocumented online/status semantics | `service/chadboard/radar.py:70`, `web/src/RadarPanel.tsx:37` | Preserve flags, use explicit seat-detail fields, name swarm vs detail observations and their retrieval time; live lookup inspected |
| Medium: malformed optional service/recovery data could crash rendering or create an unsafe evidence link | `web/src/radar-data.ts:15`, `web/src/feed.ts:95` | Validate structures and fixed Radar source URLs; malformed enrichment is rejected without losing Ethereum rows; unit/browser tests pass |
| Medium: shared SQLite connection could expose a writer's uncommitted snapshot to API reads | `service/chadboard/api.py:390` | Per-request read-only connection and consistent read transaction; HTTP integration and an uncommitted-snapshot isolation test pass |

No unresolved first-screen or repeated visual failure was observed in Chromium.
One control was below the comfortable 44px target but passed the probe's 24px/
spacing rule. No ignored-file change or new dependency was needed for these fixes.

## Retained evidence and submission integrity

- `mobile-390.png`, `desktop-1440.png`, `radar-live-390.png`: actual production page and cached source lookup via browser MCP.
- `radar-live-check.json`: public source provenance and bounded cache-smoke results.
- `archive-preflight.json`: precise historical probes, count scope, gaps and estimate.
- `chromium-interactions.json`, `taste-checks.json`: copied actual final check reports.
- Disposable screenshots, cache databases and browser runtime files remain outside
  the submission. Source and all required runtime assets remain complete.

The final candidate-file/secret/export comparison passes: no protected-path
changes, credential matches, dependency/cache artifacts or submodules; the export
matches the production build byte for byte. The complete candidate tree plus named
artifacts is below 2.6 MB uncompressed (below 0.8 MB as a review archive), within
the 8 MiB budget. The durable summary is in `docs/RADAR-VALIDATION.json` under
`submissionIntegrity`; the exact measurement is in `artifacts/submission-check.json`. The worker’s pre-existing `.git/info/exclude` excludes
`artifacts/`; that protected file was not changed. Required named artifacts remain
in that directory for artifact delivery, and the current report plus machine-readable
check summaries are also retained as normal repository documentation in
`docs/VALIDATION.md` and `docs/RADAR-VALIDATION.json`. No ignore file was changed. No protected build/dependency file, `.github`, `.env`,
`.git`, `lib/` or `node_modules/` was changed, and no submodule or ignore rule was
introduced. The archive URL is absent from the source/export candidate scan.

Completion: **adapter and static website implemented and Chromium-validated;
full mainnet backfill and WebKit validation remain incomplete for the explicit
runtime/provider reasons above.**
