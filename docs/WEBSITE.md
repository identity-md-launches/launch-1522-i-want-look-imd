# ChadBoard website

The static site in `dist/` queries the existing Ethereum IMDChadBoard. The new
frontend lives in `web/`; the Solidity contracts, indexer, deployment manifest
and existing build configuration are unchanged.

## Install, preview and rebuild

Use Node 22.12 or newer and npm. From the repository root:

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
npm run preview
```

Open the local preview URL printed by Vite. `npm run dev` runs the development
server. The production build replaces repository-root `dist/`. Publish that
directory as static files. No server rewrite is required: navigation uses anchors,
Vite's base is `./`, and JavaScript, CSS, favicon and share-card URLs are relative.
Serve over HTTP(S), rather than opening `index.html` as a `file:` URL.

Keep `web/package.json`, `web/package-lock.json`, all frontend source, and the
complete `dist/` export together. Do not include `node_modules`, package caches,
Playwright browsers, test screenshots or downloaded system libraries in a source
submission. The package lock resolves ordinary npm dependencies; an initial
`npm ci` needs registry access or an already populated npm cache. Rebuilding after
installation does not fetch remote fonts or assets. No vendored npm registry is
needed. No ignore files were changed in this assignment.

For this restricted worker run, installation and compilation happened in a
scratch copy outside the repository. That preserved all existing configuration
and kept dependency/cache files outside the submission. The resulting export is
copied byte-for-byte to `dist/`.

## Query and payment behavior

| Query | Interface fee |
| --- | ---: |
| Wallet list, up to 100 unique addresses | 0.1 IMD per unique requested wallet |
| Top 10 | 0.1 IMD |
| Top 50 | 0.5 IMD |
| Top 100 | 1 IMD |
| Top 1,000 | 2 IMD |

These pack prices are implementation choices within the requested maximum of
2 IMD. Duplicate addresses are billed once. A mixed wallet query includes an
explicit matched/requested count before payment and costs the number of unique
requested wallets, including absent ones. A leaderboard returns up to its chosen
size; the actual count is shown before payment.

The requester supplied this recipient:
`0x000000000000000000000000000000000000dEaD`.
The wallet submits an exact-value ERC-20 `transfer` of the existing IMD token
straight to this address. There is no allowance, router, fee-collecting contract,
intermediary custody or new deployment. Sending to this address does not call a
token burn function and does not reduce ERC-20 `totalSupply`. Ethereum gas is
additional and is estimated by the visitor's wallet.

Flow:

1. Validate addresses or select a leaderboard size.
2. Verify Ethereum chain ID, the board's exact runtime-code hash, IMD code and
   decimals; read one current published epoch.
3. Read all requested results from that immutable epoch before asking for money.
   Reject missing/stale configuration, no snapshot or entirely absent results.
4. Show the amount, actual matched count, snapshot block, full recipient and
   irreversibility. Require a separate consent checkbox.
5. Connect an injected EIP-1193/EIP-6963 browser wallet and switch to Ethereum if
   necessary. Recheck account, chain and current epoch, check IMD balance, and
   simulate the exact transfer before requesting a transaction.
6. Wait for two confirmations and verify the successful receipt's hash, sender,
   token recipient and exact IMD `Transfer` event to the dead address.
7. Show results with provenance, metric details, address filtering, pagination,
   JSON and CSV downloads.

Top 1,000 uses ten calls of at most 100 entries, respecting the contract's
`MAX_PAGE`. Wallet reads use five concurrent wallets per batch. All addresses in
production configuration come from the pinned deployment/network inputs, except
the expressly supplied dead recipient. Test addresses occur only in test fixtures.

## Live status and limitations

On **2026-10-13 at Ethereum block 26183635**, the live contract reported
`latestEpoch = 0` and `configuration = 0`. The board is deployed but its operator
has not configured/published its first snapshot. The site honestly displays this
state and will not request a query payment until usable current results exist.
The existing owner/reporter configuration and indexing workflow remains in the
original repository documentation. This website does not configure or publish
snapshots for the operator.

The read functions are public. The charge is an **interface policy**, not an
on-chain access-control guarantee. A static website cannot make this public data
private. The site says this before payment and in its help. No real wallet
transaction was signed or sent during implementation. Payment-success tests use
clearly isolated provider and RPC fixtures, never seeded production rankings.

Snapshot history is attested by the appointed reporter. The contract checks
accounting and ordering, not historical completeness. The score is scaled from
0–10,000 to 0–100. Claim delays are capped at 30 days per claim. App events show
recognized on-chain activity, not browsing or connecting a wallet. Token reports
show full quantities in their native decimals; unavailable metadata falls back
to raw units and the token's address.

The site supports browser extensions and in-wallet browsers. It does not include
WalletConnect/QR bridging. If no provider is present it gives an actionable
message. Connecting discloses a public address and never authorizes a payment.

Pending transaction hashes and prepared reports persist in local storage.
Confirmation failure or an uncertain receipt never automatically sends a second
payment. The visitor can retry the receipt check, supply a replacement hash or
explicitly discard a cancelled/reverted local record. A downloadable recovery
JSON can be restored using “Where are my results saved?”; the receipt is checked
again, while the prepared report is read from the visitor's own file. Browser
storage/imported files are not cryptographic attestations of report contents.
Confirmed results remain in the current tab and can be downloaded. There is no
shared backend, analytics server or secret configuration.

RPC availability and a configured reporting operator are external dependencies.
Public RPC providers receive queried addresses. A chain reorganization after two
confirmations is still possible. Results identify the immutable observation block
and do not claim to reflect real-time balances. If the observed epoch changes
before sending, the visitor must review a newly prepared query.

## Verification commands

The full results and six-domain design review are in
[`WEBSITE-VALIDATION.md`](WEBSITE-VALIDATION.md). The design system is in
[`../DESIGN.md`](../DESIGN.md).

Seven meaningful unit tests run with `npm test`. The ABI test canonicalizes
object keys recursively (array order unchanged) and checks the pinned keccak hash.
The receipt tests reject wrong tokens, senders, recipients, amounts, hashes and
reverted transactions. The recovery parser rejects malformed inputs.

Read-only live verification, from `web/`:

```sh
npx tsx scripts/verify-deployment.ts
```

An operator may append `--rpc <their RPC URL>`; the script does not print the URL.
It reads code/state and never signs or sends transactions. Worker validation used
the provided local relay. The public source is
`https://ethereum-rpc.publicnode.com`, with `https://eth.drpc.org` configured as
fallback for visitors. No machine-local relay address is shipped in the site.

To rerun the production interaction suite without installing browser dependencies
in this repository, install Playwright and axe in an external directory:

```sh
npm install --prefix /tmp/chadboard-checks playwright@1.56.1 @axe-core/playwright@4.10.2
PLAYWRIGHT_BROWSERS_PATH=/tmp/chadboard-browsers \
  /tmp/chadboard-checks/node_modules/.bin/playwright install chromium webkit
cd web
PLAYWRIGHT_BROWSERS_PATH=/tmp/chadboard-browsers \
IMD_PLAYWRIGHT=/tmp/chadboard-checks/node_modules/playwright/index.mjs \
IMD_AXE=/tmp/chadboard-checks/node_modules/@axe-core/playwright/dist/index.mjs \
  npx tsx scripts/check-browser.ts
```

Repeat with `IMD_BROWSER=webkit` to use WebKit. System libraries are required for
both engines. The browser suite owns a temporary foreground HTTP server, serves
`../dist/` at `/preview/`, intercepts every external request, uses deterministic
RPC/wallet fixtures and closes the server/browser on completion. It writes only
`test/scratch/browser/` by default. Set `IMD_BROWSER_OUTPUT` to another scratch
directory for the second engine. `IMD_EXPORT` can name a different export.
The tests do not contact public RPCs or spend funds.

While the job's pinned design probe remains available, run from the repository
root with the same browser environment:

```sh
node .imd/reads/skills/design-critic/scripts/taste.mjs --out test/scratch/taste
```

The worker-provided `.imd/reads/` inputs and `test/scratch/` are not deliverables.
Recorded findings and commands are retained in documentation instead.

## Public deployment provenance

| Item | Value |
| --- | --- |
| Chain | Ethereum mainnet, ID 1 |
| Board | `0xd27c1f25427a04db405db956fd8b859a53784f28` |
| Existing IMD token | `0xd34a99bc0f67ae1bbd63c660e6d0b0dd03e263b7` |
| Token decimals | 18 |
| Pinned source commit | `061eccd99cb9b1cd380ea1f0a7f76231fd308bde` |
| Canonical ABI keccak | `0x9890f956e09de6e033bcf8c2637ffea83209159f5c1627f59822906de5e21ad8` |
| Runtime keccak | `0xc671c848cccbc703c054231199de354a6fdf48b90c39b0154979772711ae740b` |
| Runtime bytes | 14,700 |

The ABI in `web/src/board-abi.ts` was generated with `forge inspect IMDChadBoard
abi --json` from the supplied contract source. Its canonical hash exactly matched
the pinned deployment. `forge inspect IMDChadBoard deployedBytecode` exactly matched
the bytes fetched from the live address. The runtime fixture in `web/tests/fixtures/`
is that bytecode and is used only by the browser tests.
