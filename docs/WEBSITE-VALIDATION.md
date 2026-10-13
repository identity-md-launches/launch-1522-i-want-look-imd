# Website validation and design review

Worker verification on 2026-10-13. These are reproducible worker-side observations,
not independent network certification.

## Scope and outcome

**Complete for the website assignment.** The supplied dead recipient is wired
into the new static query interface. The existing contracts, indexer, deployment
manifest, Foundry configuration and dependencies were preserved. No contract was
deployed, no token was replaced, and no mainnet transaction was sent.

The Ethereum board is deployed but has **no published snapshot**. At block
26183635, `latestEpoch()` and `configuration()` both returned zero. The interface
reports unavailable rankings honestly and pauses payments until the operator
publishes current data. Operator publication is external to this frontend task,
not replaced by sample data. All successful wallet/leaderboard examples used in
interaction tests are isolated test fixtures and are absent from production.

Implemented pricing decisions: 0.1 IMD per unique requested wallet (maximum 100
per batch), and fixed 0.1/0.5/1/2 IMD prices for Top 10/50/100/1,000. Preflight
shows the number of available results before an irreversible transfer. The page
explains the public-read trust model and interface-only fee policy. The visual
direction was inferred because the project had no earlier frontend: a compact
query tool on warm paper, ink typography and one violet action, with a static
scoring-weight explanation beside the desktop form.

## Actual build and integrity checks

| Check | Actual result |
| --- | --- |
| `npm ci --offline --ignore-scripts --no-audit --no-fund --cache /tmp/imd-npm-cache` in a fresh scratch copy of `web/` | Exit 0; 85 packages installed from the populated cache using the committed lockfile |
| `npm run typecheck` | Exit 0; TypeScript strict checks over production source |
| `npm test` | Exit 0; 7 tests, 7 passed |
| `npm run build` | Exit 0; Vite production export, 1,097 modules; no chunk-size warning after separating dependencies |
| Production export vs fresh lockfile build | All seven file hashes identical; 574,593 uncompressed bytes |
| Source path/dependency inspection | No `node_modules`, caches, `.tgz`/`.deb` archives or symlinks in submission candidates; no submodule added; no ignore file modified |
| Existing tracked-file diff | Only README changed; Solidity, tests, indexer, build configuration, existing libraries and manifest unchanged |
| Bundle budget | Approximately 2 MB of source plus export before compression, below 8,388,608 bytes; no validation screenshots or browser downloads included |
| ABI canonical hash | Exactly `0x9890f956e09de6e033bcf8c2637ffea83209159f5c1627f59822906de5e21ad8`, matching pinned deployment |
| Live board code | Exact byte-for-byte match to `forge inspect` runtime; 14,700 bytes, keccak `0xc671c848cccbc703c054231199de354a6fdf48b90c39b0154979772711ae740b` |
| IMD token read | Chain ID 1, nonempty code, symbol IMD, decimals 18 |
| HTML/export metadata | Title, description, SVG favicon, og:title, 1200×630 PNG og:image present; JS/CSS/image paths relative |

Initial dependency installation and browser downloads used network access, with
all dependency/cache directories outside the repository. The final installation
and production build used the cached lockfile packages offline. Final `dist/`
contains only the page, favicon, share card and four hashed runtime assets. The
editable share-card SVG stays under `web/assets/`, not in the export.

The none execution profile does not require a new Foundry suite for this website.
Foundry was used to derive the ABI and runtime for comparison; no claim is made
that the unrelated existing Solidity/Python test suites were rerun in this task.

## Interaction and rendered checks

`web/scripts/check-browser.ts` was run against the production export at a local
`/preview/` subpath, first with Chromium 141 (Playwright build 1194), then WebKit 26
(build 2215). **17 grouped interaction checks passed in each engine.** The harness
owns and closes its preview server and intercepts all RPC/provider calls with
clearly identified fixtures; it cannot sign a real transaction.

Coverage:

- Static relative assets load; first-screen primary action visible at 390×844.
- Empty view reflows at 320, 390, 820 and 1440px. Report grids also reflow at all
  four widths. No horizontal document overflow in those checks.
- Keyboard skip link reaches the query. Query buttons, native leaderboard radios,
  dialog close/Escape and focus return work. The focused query tab was inspected
  in a screenshot. Native controls provide accessible roles/names.
- 200% root text enlargement reflows at 390px after the header/tab fixes. Reduced
  motion produces no button transition. This is distinct from browser-native zoom.
- Empty/invalid/checksum/batch inputs, deduplication and exact pricing; all four
  pack selections and arrow-key radio movement.
- Empty board, stale epoch, noncurrent configuration, entirely absent wallets,
  code mismatch and RPC failure prevent payment. Refresh recovers after an RPC
  error. Unknown data is labeled unavailable, never invented zero activity.
- No-wallet fallback, EIP-6963 provider selection, connection, wrong-network
  switch, explicit amount/recipient review and unchecked-consent blocking.
- Insufficient IMD, a changed epoch, a changed account and a rejected signature
  leave the query unpaid. The encoded transaction calls only IMD `transfer`, with
  zero ETH value and the exact recipient/amount.
- Pending state blocks a second payment. Reload retains the reference and
  retrieves the receipt without another wallet send. Failed receipt validation
  keeps the pending record, and retry after a matching receipt succeeds.
- Paid wallet metrics, claim timing, token holdings/transfers, provenance,
  filtering/clear action and JSON/CSV downloads with content assertions.
- Top 1,000 fetches exactly ten pages at offsets 0–900 and costs 2 IMD. The screen
  paginates 25 rows at a time; Next shows rank 26 on page 2 of 40.
- Recovery file download/import, invalid-file rejection and retrieval without a
  new payment. Report contents come from the visitor's own saved file; the
  receipt is independently read and checked.
- No uncaught JS exceptions, local console errors or failed local resources.
  The deliberately induced RPC 503 failures are part of the recovery test.

Axe 4.10.2 reported **zero violations** on the empty view, payment review and
wallet-results view with expanded provenance in each browser. This is an automated check, not a
claim of complete WCAG compliance or a screen-reader session.

Actual invocation (environment paths were task-local scratch installations):

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/imd-playwright-browsers \
IMD_PLAYWRIGHT=/tmp/imd-chadboard-checks/node_modules/playwright/index.mjs \
IMD_AXE=/tmp/imd-chadboard-checks/node_modules/@axe-core/playwright/dist/index.mjs \
  node_modules/.bin/tsx scripts/check-browser.ts
```

The second run used `IMD_BROWSER=webkit`, a separate scratch output directory and
`LD_LIBRARY_PATH` pointing to temporary Ubuntu runtime libraries. The supplied
browser MCP returned “Transport closed.” Direct Playwright supplied the rendered
checks. WebKit initially lacked libraries; they were unpacked in `/tmp/`, and its
temporary launcher preserved that library path. No system or repository build
configuration was changed to enable the browser. Run the two engines sequentially
to avoid tsx's temporary IPC-name collisions in this worker environment.

Evidence generated and inspected under disposable scratch paths:

- `test/scratch/browser/empty-{320,390,820,1440}.png`
- `test/scratch/browser/keyboard-focus.png`, `text-200-percent.png`
- `test/scratch/browser/payment-review-mock.png`, `wallet-results-mock.png`,
  `leaderboard-results-mock.png`
- Corresponding `test/scratch/webkit/` screenshots and interaction results.
- `axe-empty.json`, `axe-review.json`, `axe-results.json` and
  `interaction-results.json` in each browser output directory.
- `test/scratch/taste/shots/` and `test/scratch/taste/taste.json`.

Scratch evidence is removed by the worker before submission. Reusable check
scripts, fixture data and this written record remain in the source bundle.

## Better Interface: six-domain coverage

The pinned workflow and all six domains' core principles were read before the
interface was finalized. The visual idea is the same throughout: a compact
participation report whose form, cost and action take precedence over explanation.

| Domain | Status and evidence | Remaining coverage limits |
| --- | --- | --- |
| Accessibility | Checked native landmarks, labels, form errors, live regions, native radios/disclosures/dialog, keyboard path and visible focus; axe empty/review/results = 0 violations | No physical screen-reader session, hardware keyboard/device matrix, forced-colors rendering or native 200% zoom test |
| Layout | Checked primary control at 390×844; source grid/DOM order and rendered 320/390/820/1440 widths; results, dialog and 200% root-text reflow | Only English/LTR implemented; no pseudolocalization or RTL-mirror test |
| Writing | Checked action labels, explicit matched counts and fees, missing/stale/error/retry messages, irreversible recipient review, public-read and reporter trust disclosures | No user research or translation testing |
| Typography | Checked six declared sizes, two weights, sans UI/mono addresses, input size, tabular numbers and full address wrapping; probe passes | System fallback font rendering varies by device; no locally bundled font |
| Colors | Checked semantic tokens and actual solid backgrounds in screenshots; probe text-contrast check and axe passes | Not every transient hover/disabled pair measured individually; one deliberate light theme |
| UI | Checked hover/focus/selected/loading/empty/pending/rejected/success patterns; flat border surfaces and opt-in 120ms press transition; reduced-motion check passes | No physical touch hardware or animation-panel slow playback; no theme switching/autoplay, so those guide sections are not applicable |

Measured rendered pairs from the final probe:

| Text / background | Contrast | Required |
| --- | ---: | ---: |
| Main title `#272438` on page `#f6f5f1` | 13.79:1 | 3:1 large text |
| Query label `#625e69` on white surface | 6.32:1 | 4.5:1 |
| Primary text white on `#6543b3` | 6.98:1 | 4.5:1 |

The product remains usable with JavaScript-enabled Chromium/WebKit at the tested
sizes. A noscript message states why JavaScript is required.

## Findings, corrections and rechecks

| Finding | Source | Reproduction / impact | Correction and outcome |
| --- | --- | --- | --- |
| High: enlarged-text overflow | `web/src/styles.css:294`, `web/src/styles.css:986` | At 390px with root text at 200%, the header and query selector could exceed the viewport; the Leaderboard control was outside the layout | Allowed header and query buttons to wrap. Rechecked in both engines with 200% text and no horizontal overflow; normal 320/390/820/1440 views remain intact |
| High: focus lost after dismissing a dialog | `web/src/App.tsx:90` | Connect-wallet dialog closed on Escape but the opener lost focus after React unmounted the native dialog | Capture the opener and explicitly restore focus in dialog cleanup. Both browsers assert focus returns to Connect wallet; screenshot confirms query focus indicator |
| Medium: unknown census must not imply unpublished data | `web/src/App.tsx:220` | The original overview fallback used “Not published” even for a loading/failed RPC read, conflating unknown with on-chain absence | Separate “Checking…”, “Unavailable” and “Not published”. RPC failure/refresh test asserts the unavailable state and recovery |

The initial unit-test fixture incorrectly treated an arbitrary all-uppercase
address as a valid strict-checksum input. The test was corrected to exercise a
proper checksummed address; invalid checksums remain rejected with an explicit
lowercase/checksum hint. A test-provider injection initially carried tsx helper
references into the browser; moving the fake wallet to an ordinary JS fixture
fixed the harness. Neither fixture appears in production assets.

No applicable high/medium design findings remain from this review. The probe
reports one control below its comfortable 44px target: the isolated brand/home
link. It is above the 24px baseline and has sufficient separation; primary
controls are at least 44px.

## Final pinned probe

From the repository root, with the external Playwright environment configured:

```sh
node .imd/reads/skills/design-critic/scripts/taste.mjs --out test/scratch/taste
```

**16/16 checks passed** after the last production-source change: render, layout,
targets, contrast, casing, tracking, eyebrows, type sizes, type faces, glyphs,
slogans, repetition, copy budget, chrome, motion and share metadata. No horizontal
overflow at 320/390/1440, text overlaps, clipped text, covered text, local resource
failures, nested decorative cards or infinite motion were reported. The first
390px screen contains 28 prose words (limit 60). At 1440 it contains 40 (limit 90).
The 390px screen and 1440px desktop composition were visually inspected; the
share PNG and payment-review screenshot were inspected separately.

## Limits and handoff

No real browser wallet or hardware device signed a transaction. Mainnet code and
state were verified read-only using the worker relay; the public endpoint named
as source is `https://ethereum-rpc.publicnode.com`. Successful chain data and
payment states were exercised using deterministic fixtures because the live
board has no epoch. No fake data is served in the production site.

No screen reader, physical iPhone, browser-native zoom, locale/RTL matrix or
external social-unfurl service was tested. The relative share-card URL resolves
under the tested subpath; platform-specific unfurl behavior is not claimed.
Accessibility automation is bounded evidence. Public RPC reliability, future
snapshot publication and chain finality remain external dependencies.

`README.md` and `docs/WEBSITE.md` explain installation and rebuilding;
`DESIGN.md` records the final implemented tokens, typography, components and
responsive behavior. Source, lockfile and ready-to-host export are present and
unignored for the worker's submission commit. This task does not publish the site.
