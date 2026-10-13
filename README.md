# IMD seat and wallet analytics

`IMDChadBoard` publishes an auditable census of activated IMD NFT seats and a
ranked, 0–10,000 “chadness” score for their associated wallets. It exposes both
paged leaderboards and a single-wallet query. The accompanying indexer reads
finalized Ethereum logs, computes the observations, and prepares unsigned
publication transactions. There is one application contract and no new token,
pool, distributor, proxy, fund custody, or reward allocation.

**This is an attested analytics service.** The owner appoints the reporting
operator. Historical events and website visits are not available to an EVM
contract by introspection. The board verifies accounting, scores, ordering,
configuration and publication completeness; it does not prove that the reporter
included all real activity. Every snapshot identifies its observation block,
reporter, methodology, configuration and evidence hash. Consumers must display
its age and trust model.

## Website: query wallets and send fees to the dead address

The static website is in **`dist/index.html`**, with React/TypeScript source and
its npm lockfile in `web/`. It connects to the existing Ethereum board and IMD
token. The supplied recipient is
`0x000000000000000000000000000000000000dEaD`.

To install, check, rebuild and preview (Node 22.12+):

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
npm run preview
```

The build writes repository-root `dist/`. Serve that directory over HTTP(S);
relative assets and anchor navigation support static hosting at a subpath.
The installation initially needs the npm registry or a populated cache. Do not
include dependency or cache directories in a Git submission.

Wallet lists cost 0.1 IMD per unique address. Top 10/50/100/1,000 cost
0.1/0.5/1/2 IMD respectively. The interface checks availability, shows the exact
fee and recipient, requests consent, sends an ERC-20 transfer and validates its
receipt before displaying results. No token approval or new contract is involved.
Results support metric details, filtering, pagination, JSON/CSV downloads and
pending-payment recovery.

**Live availability:** at Ethereum block 26183635 on 2026-10-13, the deployed
board had no published epoch and configuration was unset. Payments remain paused
until its operator publishes a current snapshot. The website does not invent
rankings or collect fees for unavailable data. Its fee is an interface policy;
underlying contract reads are public.

The original website validation is preserved below; current build, adapter,
interaction and design-review results are recorded in
[docs/VALIDATION.md](docs/VALIDATION.md). No real payment was signed or sent. See
[website operation and rebuild instructions](docs/WEBSITE.md),
[actual validation results and limitations](docs/WEBSITE-VALIDATION.md), and
[implemented design system](DESIGN.md).

## Optional IMD Radar enrichment

The existing interface now exposes **Data sources · Ethereum rankings**, with a
seat/wallet lookup, cached source evidence, stale warnings, explicit disagreements
and liquidity-filtered launch estimates. Enable the optional server adapter with
`CHADBOARD_RADAR_ENABLED=1`. Radar cannot change a score, ranked wallet set,
immutable ordering, IMD balance, Transfer ledger or sale/retention classification.
The site and Ethereum service continue to work when Radar is disabled or offline.

From the repository root (Python 3.10+, no additional Python packages):

```sh
PYTHONPATH=service CHADBOARD_RADAR_ENABLED=1 python3 -m chadboard radar
PYTHONPATH=service CHADBOARD_RADAR_ENABLED=1 python3 -m chadboard serve
python3 -m unittest discover -s service/tests -v
```

Connect that service using the site's source disclosure or the existing `#api=`
setting. See [adapter/API/configuration details](docs/RADAR.md),
[service operations](docs/SERVICE.md), and [current validation](docs/VALIDATION.md).
Keep `ETH_ARCHIVE_RPC_URL` in the server environment only; never use a `VITE_`
variable for it. Run `PYTHONPATH=service python3 -m chadboard preflight` before
starting historical indexing, then inspect `PYTHONPATH=service python3 -m chadboard coverage`.

**Historical coverage limitation:** the supplied archive provider permits only
10-block log ranges. The worker verified historical blocks and sample Transfer
windows from **23,501,863 through 26,184,642**, but did not complete the full scan.
The samples contain **8 events / 11 unique nonzero counterparties**, not
whole-history totals. The exact gaps, dry-run and request estimate are in
[the archive report](docs/RADAR-VALIDATION.json). No sample was promoted to
a complete ranking. The existing holding heuristic remains separate from the
ChadBoard contract's published participation score; the UI labels the distinction.

## What is measured

| Question | Delivered observation |
| --- | --- |
| How many seats exist and are activated? | Existing, unburned ERC-721 seats; current activated seats; unique associated wallets; active seats per wallet. Multiple seats do not multiply a wallet's score. |
| How many IMD launch tasks were initiated? | Distinct initiation IDs emitted by configured IMD launch sources, attributed to the initiator wallet. |
| How long until rewards were claimed? | First nonzero claim time minus **eligibility time**, for each distinct reward allocation. The board stores counts, total delay, and maximum delay, with each allocation's delay **capped at 30 days** before it is summed; its query tool also returns the average of those capped seconds. The evidence report includes each allocation's raw timestamps, amount, received amount, and pending status. |
| Sold or still holding rewards? | Claimed units, attributed reward units still held, reward units sold through recognized venues, reward units otherwise transferred/burned, and actual wallet balance at the snapshot block, per token. |
| Bought extra ecosystem tokens? | Gross purchased units from recognized buy events matched to actual incoming token transfers. Gifts and reward claims do not count as purchases. |
| Used an ecosystem website? | Successful on-chain interactions with configured app event sources, plus distinct app identities. **Browsing a website or connecting a wallet is not observable on-chain.** |

Metrics cover `start_block` through the finalized snapshot block, including a
wallet's activity before its seat activation. Only wallets associated with
currently activated seats are included in that snapshot. NFT transfers,
deactivations and association changes affect the next census; previous snapshots
remain immutable. The policy explicitly chooses whether association follows the
NFT owner or an activation beneficiary, and whether transfer clears activation.

Fungible token units have no unique provenance. The documented estimate consumes
rewards **first** on each outgoing transfer, in canonical log order. An outgoing
recognized sale consumes `rewardSold`; other outgoing transfers consume
`rewardOtherOut`. Repurchases and gifts do not restore rewards already disposed
of. Therefore `rewardHeld + rewardSold + rewardOtherOut == claimed` and
`rewardHeld <= balance`. An unclassified transfer to an exchange, bridge or
contract is not asserted to be a sale. All amounts use each token's native units.

## Build and check

Run from the repository root with Foundry and Python 3.10+:

```sh
forge build
forge test
forge fmt --check
python3 -m unittest discover -s test -p 'test_*.py' -v
```

The compiler is pinned to Solidity 0.8.26, with optimization, IR compilation and
`bytecode_hash = "none"`. The verifier must supply that compiler, as specified by
the assignment. `forge-std` v1.9.7 is vendored as ordinary files in `lib/`; there
are no downloads needed for building or testing. Production Solidity and Python
have no third-party library dependencies. The CLI uses the installed `cast` only
for ABI encoding, not signing. The Python integration test starts a private
loopback Anvil and uses its unlocked test accounts. Test contracts under
`test/fixtures/` are deliberately unrestricted and are **not application
contracts**.

Tests cover authorization, two-step ownership, unset dependencies, immutable
history, atomic publication, duplicates, batch rollback, sorting and ties,
pagination, stale data, configuration races, reporter revocation during a
pending draft, reward accounting, decimal differences, dust-claim weighting,
maximum input sizes and fuzzed score bounds/monotonicity (more disposals never
raise a score; one more claim never lowers it). Indexer tests cover finalized
reads, reorgs, eligibility and partial claims, capped late claims, transfer
classification, equal same-kind transfers in one transaction, NFT association
changes, missing history, re-emitted launch IDs, ambiguous transfers and all
five metrics. A real local EVM test exercises the complete pipeline from
emitted logs through publication and decoded queries.

## Deployment

Deploy **only `IMDChadBoard`**, from `src/IMDChadBoard.sol`, on Ethereum (chain ID
1). It has one nonpayable constructor argument:

| Argument | Value |
| --- | --- |
| `address initialOwner` | `$owner`, resolving to the launch's specified owner `0x568fe872c046cf79d713323c290e33f9906b8590` |

The constructor makes no external calls and does not assume that dependencies
already have code. The factory and transaction origin receive no privileges.
There are no linked libraries, creation of child contracts, initializer calls,
upgrade paths or forbidden execution opcodes. The separate launch process
produces the manifest and confirmed deployment address; this project neither
creates `launch.json` nor broadcasts a deployment.

The source contract addresses, actual event ABIs, reporter and token set were not
provided. They are owner-settable settings, not fabricated deployment arguments.
The constructor leaves them explicitly unconfigured, and publication reverts
with `NotConfigured` until real dependencies are supplied. These operational
settings do not initialize ownership or enable a second initialization path.

## After launch

The owner must obtain the actual Ethereum addresses and ABIs from the IMD
deployment records and the ecosystem's contract maintainers. The owner/operator
must map their events into the schema in [docs/INDEXER.md](docs/INDEXER.md).

| Setter | What to supply / where it comes from |
| --- | --- |
| `setSources(address nft, bytes32 policyHash)` | Actual IMD ERC-721 seat contract; SHA-256 of the reviewed canonical indexing policy from `policy-hash`. The policy binds the registry/activation events, launch and claim sources, token contracts, venues, apps, observation start and association semantics. |
| `setTokenPolicies(TokenPolicy[] policies)` | The exact sorted, unique token addresses from that policy, with a nonzero `supportTarget` in native units for each. Obtain decimals and deployed addresses from the token maintainers and independently verify them. Owner chooses and publishes the support thresholds. Maximum 16 tokens. |
| `setReporter(address reporter)` | The owner's designated operational signer or multisig. The application never chooses or owns this signer. The operator runs the indexer and pays publication gas. Setting zero explicitly **revokes** reporting; it is not a deployment stand-in. Any call aborts a pending draft first, so rotate only between publications unless you intend to discard the draft. |
| `setMaxAge(uint64 seconds)` | Optional freshness requirement; default 2 days, permitted 1 hour–30 days. Set to match the actual publication schedule. |

All configuration changes emit events, advance a configuration revision, and
make existing snapshots report `currentConfiguration = false` and `stale = true`.
Historical scoring inputs and results do not change. Sources, token policies and
`maxAge` cannot change while a draft exists: finish it or abort it first.
`setReporter` is the exception: it aborts any pending draft in the same
transaction (emitting `EpochAborted`) before writing the new reporter, so a
stalled or compromised reporter that keeps re-opening drafts cannot block its own
revocation or rotation. Once the reporter is revoked, no draft can be opened and
the other setters are free again. Ownership handover requires
`transferOwnership` and acceptance by the nominated new owner. There is no
renounce function or privileged wallet-score override.

## Operate and query

The following shell variables refer to real operator-supplied values:
`RPC_URL` is an Ethereum archive RPC with finalized/EIP-1898 support, `BOARD` is
the confirmed deployment address, and `WALLET` is the address being queried.
Create `policy.json` using the schema documentation and actual deployment ABIs.
Do not commit RPC credentials or signing keys.

```sh
python3 tools/imd_indexer.py policy-hash --policy policy.json
python3 tools/imd_indexer.py scan --policy policy.json --rpc "$RPC_URL" --output report.json
python3 tools/imd_indexer.py prepare --report report.json --rpc "$RPC_URL" --board "$BOARD" --output calls.json
```

`scan` and `prepare` make only read-only RPC requests. `prepare` checks the
configured policy, token order/thresholds, scores, canonical finalized block,
report ordering and expected configuration; it simulates `beginEpoch`. It emits
unsigned zero-value calldata for `beginEpoch`, bounded `appendWallets` batches
and `finalizeEpoch`. The configured reporter must review and submit those calls
in order using their own transaction workflow. Estimate each batch's gas and
reduce `--batch-size` if necessary; use small batches for large token sets. The
limit is 20 rows per call, not a promise that every chain's gas ceiling permits
every maximum-size batch. Partial drafts are never public rankings.

Keep the exact canonical report available to readers. Its SHA-256, excluding the
CLI's trailing newline, is stored as `evidenceHash`. Its source log digest and
policy let another operator reproduce the scan. Hashes bind evidence; they do
not provide its availability or make it cryptographically verified chain data.
Schedule scans and publications outside this project, frequently enough to stay
inside `maxAge`, and monitor failures and missing publication receipts. A stopped
operator leaves the last published results readable and marked stale.

Anyone can query, without an indexer or privileged signer:

```sh
python3 tools/imd_indexer.py query --rpc "$RPC_URL" --board "$BOARD" --limit 20
python3 tools/imd_indexer.py query --rpc "$RPC_URL" --board "$BOARD" --wallet "$WALLET"
```

Use `--offset`/`--limit` for subsequent leaderboard pages and `--epoch` for an
immutable historical snapshot. Each invocation pins its contract reads to one
block. Single-wallet output includes rank, score, tier, claim delay, all metrics
and token balances/dispositions, with snapshot and freshness metadata. An absent
wallet has `found = false`, rank 0 and an empty portfolio; this does not assert
that it has no on-chain activity.

Direct contract APIs are `summary()`, `walletRating(address)`,
`walletAt(uint64,address)`, `walletTokens(uint64,address)`,
`epochTokenPolicies(uint64)` and `leaderboard(uint64,uint32,uint32)`. Read
`latestEpoch()` once and use that same epoch for related calls. Leaderboard pages
contain up to 100 rows; rank is one-based and page offset is zero-based.

## Scoring version 1

Scoring is fixed in the bytecode. There are no prices, token transfers, reward
payments or financial benefits attached to a score. Every division rounds down.

| Component | Maximum | Rule |
| --- | ---: | --- |
| Launches | 3,000 | `100 * min(launches, 30)` |
| Prompt claims | 1,500 | Let `C = claimedClaims`, `E = eligibleClaims`, `W = 30 days` and `T = totalClaimDelay`, where `T` is the sum over claimed allocations of `min(delay, W)`. If C is zero, 0. Otherwise `floor(1500 * (W * C - T) / (W * E))`, which equals `1500 * sum(W - min(delay_i, W)) / (W * E)`. Unclaimed allocations lower the completion fraction, and claiming an outstanding allocation, however late, never lowers the score. The board rejects `maxClaimDelay > W`. |
| Reward retention | 3,000 | For each token with claimed rewards, `floor(rewardHeld * 10000 / claimed)`, weighted by `min(claimed, supportTarget) / supportTarget` (computed as `floor(min(claimed, supportTarget) * 2^128 / supportTarget)`, never zero for a nonzero claim). Divide the weighted sum by the sum of weights, then multiply by 3000/10000. No claims gives 0. A dust claim held in one token therefore cannot offset rewards sold in another. |
| Extra purchases | 1,500 | For **every configured token**, `floor(min(bought, supportTarget) * 10000 / supportTarget)`. Average the ratios, then multiply by 1500/10000. |
| Ecosystem apps | 1,000 | `100 * min(distinctApps, 10)` |

Purchase ratios weight every configured token equally; retention ratios weight
each token by its claimed size up to `supportTarget`, so `supportTarget` is
also the scale of a "full-sized" reward position. Raw amounts with different
decimals are never added together. Launches, purchases and app counts are
lifetime-in-window counters. Purchase points use gross recognized buys, so
round trips can increase them: this score is an explicit engagement heuristic,
not a Sybil-resistant, wash-trade-resistant or economic-value oracle.

Tiers are Observer (0–2499), Contributor (2500–4999), Chad (5000–7499), and
GigaChad (7500–10000). Higher scores sort first. Equal scores sort by ascending
numeric wallet address, giving stable, unique ranks without tying rank numbers.

## Limits and responsibilities

The operator must ensure complete source history, correct event mappings,
appropriate eligibility semantics, trustworthy RPC responses and published
evidence. The owner must review policy/source changes, reporter security and
support targets. Consumers must check freshness, `found`, configuration and
token units. Historical observations are only as reliable as those parties.

The reference scanner supports standard ERC-721 Transfer history, explicitly
mapped static-word activation/activity events, and ordinary non-rebasing ERC-20s
whose transfer amounts match recognized trade/claim events. Arbitrary routers,
fee-on-transfer/rebasing assets, ERC-1155 seats, compressed/consecutive mint
events, canceled/revoked reward allocations, off-chain order fills and multi-hop
wallet attribution require a separately reviewed source-specific adapter. Do
not guess missing semantics or relabel unsupported movements as sales. The
scanner refuses missing, ambiguous or inconsistent evidence; the board can
accept reports from another reviewed operator implementation with the same
documented accounting policy.

The board cannot enumerate NFT history, contact websites, verify all reporter
assertions, hold a signer or schedule its own updates. It provides a bounded
publication and query surface for that work. There is no production source
configuration or live mainnet attestation included in this delivery. The tests
and [security review notes](docs/SECURITY.md) are local verification, not an
independent security audit.
