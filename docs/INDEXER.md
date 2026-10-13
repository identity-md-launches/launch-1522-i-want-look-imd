# Indexer policy and data contract

`tools/imd_indexer.py` uses Python's standard library, plus Foundry's `cast` for
ABI encoding in `prepare`/`query`. `scan` and `policy-hash` do not need `cast`.
No component signs or broadcasts transactions. The production RPC client rejects
all methods other than chain ID, block, log, code and eth_call reads.

## Policy schema

There is deliberately no filled-in deployment policy: the real IMD addresses,
ABIs, reward tokens and application allowlist were not supplied. Configure the
following JSON keys with actual deployment data. Unknown or missing keys are
rejected. An executable synthetic policy is built by the local integration test
in `test/test_rpc_integration.py`; none of its sources are mainnet defaults.

| Root key | Required value |
| --- | --- |
| `version` | Integer 1. |
| `chain_id` | Integer 1 (Ethereum). |
| `start_block` | Nonnegative integer at or before the earliest relevant seat mint, activation, launch and reward eligibility. Use deployment records to choose it. A wallet's pre-window activity is outside the metric definition. |
| `seat_nft` | Actual, nonzero ERC-721 contract address. |
| `seat_wallet_mode` | `"owner"` to follow the NFT's current owner, or `"activation"` to use the wallet in the activation/reassociation event. This must match the actual IMD protocol. |
| `activation_survives_transfer` | Explicit boolean. If false, an ownership-changing transfer clears activation. If true, activation remains and wallet selection follows the previous field. Burns always clear activation. Self-transfers do not change association. |
| `tokens` | Array of 1–16 objects with exactly `address` and `support_target`. Addresses must be unique, numerically ascending, and different from the NFT. Targets are positive uint128 native-unit integers or decimal strings, not decimal token quantities. |
| `events` | Array of the descriptors below. At least one each of activate, launch, eligible, claim, buy, sell, interact is required. Configure deactivate too if the protocol can deactivate seats without a transfer. |

All addresses must be full `0x`-prefixed 20-byte hex strings. Topics must be full,
nonzero 32-byte hex strings. Token amounts, IDs and locations are exact integers;
do not parse large amounts through JavaScript floating-point numbers.

`methodologyHash` is SHA-256 of the complete policy object encoded as sorted-key,
compact, ASCII JSON: Python `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=True).encode("ascii")`. Whitespace in the input file does not
matter. Numeric strings versus numbers and address spelling do affect the hash.
Use `policy-hash` and retain the reviewed original policy in the report. Any
source/mapping/threshold change requires a new owner-configured policy hash.

## Event descriptors

Each descriptor has `kind`, `address` (the actual log emitter), `topic0` and
`fields`. `group`, `app` and `where` are the only optional keys. Derive topic0
from the **actual deployed ABI's** canonical event signature, for example using
`cast keccak "$CANONICAL_EVENT_SIGNATURE"`. The scanner is not tied to the
synthetic event names used in its tests.

| Kind | Exact fields | Additional descriptor data |
| --- | --- | --- |
| `activate` | `seat`; also `wallet` when mode is `activation` | Can update an existing association. Seat must exist. |
| `deactivate` | `seat` | Clears current activation. |
| `launch` | `wallet`, `id` | Nonempty `group` names the launch ID namespace. IDs count once within that namespace: a re-emitted ID for the same wallet (a retry or re-initiation) is ignored, while the same ID attributed to a different wallet aborts the scan because the descriptor is not mapping the initiator. Map the initiator, not a transaction relayer. |
| `eligible` | `wallet`, `allocation`, `token`, `amount` | Nonempty `group` names the reward allocation namespace. A positive entitlement becomes claimable at this block's timestamp. |
| `claim` | `wallet`, `allocation`, `token`, `amount`, `counterparty` | Same `group` as its eligibility source. Wallet is both beneficiary and actual token recipient. Counterparty is the token sender. |
| `buy` | `wallet`, `token`, `amount`, `counterparty` | Counterparty is the token sender/venue. Event must mean a purchase for this wallet, not a liquidity withdrawal or gift. |
| `sell` | `wallet`, `token`, `amount`, `counterparty` | Counterparty is the token receiver/venue. Event must mean a sale by this wallet, not a liquidity deposit. |
| `interact` | `wallet` | Nonempty `app` identifies the ecosystem app/site. Multiple contracts may share the same app ID. The ABI must authenticate whose interaction it represents. |

Each field maps to one of:

- `"topic:1"`, `"topic:2"`, `"topic:3"`: an indexed static ABI word.
- `"data:0"`, `"data:1"`, etc.: a zero-based static ABI word in event data.
- `{"constant": value}`: an exact uint256 value or full address, useful when a
  trusted source's token/venue is fixed rather than emitted. A zero counterparty
  is allowed **only for a real minting reward claim**, matching Transfer from the
  ERC-20 zero-address mint sentinel. It is never an unknown address default.

Address words must be canonical (top 12 bytes zero). Other fields are unsigned
integers/bytes32 IDs. Dynamic ABI values, signed swap deltas, packed fields and
traces are not decoded by this generic adapter. An ID of zero can be a genuine
contract ID; it is not an unset configuration value.

`where`, if present, is an array of conditions with exactly `field`, `op`,
`value`. `field` is a locator as above, `op` is `"eq"` or `"gt"`, and `value`
is an unsigned integer. All conditions must match. This supports excluding
zero-amount events or selecting a direction of a static ABI event. Multiple
descriptors can share emitter/topic only when their conditions are mutually
exclusive; an ambiguous match aborts the scan. Token Transfer events are reserved
and automatically decoded, so they cannot be custom descriptors.

Do not substitute ERC-20 Transfer for a buy/sell event. Standard transfers do not
prove a trade took place. For a router or multi-hop pool, the event's sender often
is not the user and the pool's recipient may be a router. Those cases need a
reviewed adapter with full receipt/trace attribution. The configurable static
decoder does not infer a wallet from a router address or silently fabricate a
trade when evidence is missing.

## Observation and accounting rules

1. Verify Ethereum chain ID and obtain the RPC's `finalized` block. Require code
   at the NFT, token and configured emitter addresses at that block. Fetch all
   relevant NFT mint/transfer/burn and activation/deactivation events from the
   configured start block. Reconstruct ownership and current associations.
2. Deduplicate physical logs and sort by block number, transaction index and log
   index. Reject conflicting duplicates, removed logs, wrong block hashes,
   nonexistent-seat activations and inconsistent NFT transfer history. A seat ID
   need not be contiguous and token ID zero is supported.
3. Determine unique current associated wallets. Query their incoming/outgoing
   ERC-20 transfers in wallet-topic groups of up to 100, plus all configured
   activity logs, in bounded block ranges. `--chunk-size` defaults to 2000; lower
   it if the RPC rejects result size. The operator must use a provider that does
   not silently truncate logs. There are no partial-results fallbacks.
4. Match each recognized claim/buy/sell event to an **exact**
   `(token, sender, recipient, amount)` Transfer in the same transaction. Match
   the transaction before processing its log order, since events often follow
   token movement. Events that demand the same movement are matched as a group:
   when the number of identical transfers equals the number of such events and
   every event has the same kind (two equal claims from one distributor, two
   equal buys from one venue in a multicall), they are paired in log order,
   because any pairing yields the same ledger. A surplus identical transfer (a
   gift beside a reward of the same amount), a shortfall, or events of mixed
   kinds competing for the same transfers abort the scan; those need a
   source-specific adapter, since choosing one would misattribute holdings.
5. Replay transfers in log order. On reward receipt, increase claimed and reward
   held. On each outgoing transfer, remove `min(amount, rewardHeld)` from reward
   held and attribute it to reward sold or reward other-out according to the
   recognized event. Track all actual sales/other outflows separately. A self
   transfer or zero transfer has no effect. Ordinary incoming transfers only
   affect the later balance read, not purchased/reward amounts.
6. Count unique initiation IDs. Record each eligibility allocation once. First
   nonzero claim determines claim latency, stored as `min(delay, 30 days)` so
   that `totalClaimDelay` and `maxClaimDelay` never exceed what the board scores
   (the per-allocation evidence keeps the raw timestamps); later partial claims
   increase token totals without duplicating claim count or changing that latency. Reject
   missing eligibility, beneficiary/token mismatches and claims exceeding the
   entitlement. Unclaimed allocations remain in `eligibleClaims`. The generic
   adapter assumes allocations are not later canceled, revoked or reassigned.
7. Count at most one interaction per wallet/app/transaction; count each app only
   once in distinct apps. Successful logs are on-chain usage evidence, not proof
   that the user visited a particular frontend domain.
8. Read every eligible wallet's `balanceOf` for every configured token using
   EIP-1898 `{blockHash, requireCanonical: true}`. Require consistent reward
   attribution and uint bounds. Recheck the canonical snapshot hash after the
   scan. If a source disappeared or a token's behavior makes attribution
   inconsistent, fail rather than pad or clamp the observations.
9. Compute the exact board score, sort by descending score then numeric address,
   assign one-based ranks, and write canonical JSON.

The scanner replays the window for each run. It does not maintain a checkpoint
that might retain a reorg or an old policy. Large histories can be expensive to
query; an operator can build an incremental indexer with rollback and retained
raw receipts, but it must implement the same policy and completeness checks.

## Publication protocol

`beginEpoch(SnapshotInput)` takes eight static fields in declaration order:
block number, timestamp, block hash, existing seats, activated seats, wallet
count, evidence hash, expected configuration revision. It requires a past,
fresh, strictly advancing block/time relative to the last published epoch, and
valid totals. A recent block hash (within the EVM's 256-block window) must match
`blockhash`; older hashes and the timestamp remain reporter attestations. The
scanner requires finality; the board does not claim to implement consensus
finality verification.

`appendWallets(epoch, reports)` accepts 1–20 rows in descending computed score
order. Equal scores use ascending numeric addresses. Each row has:

- Wallet address.
- `WalletMetrics`: active seats, launches, eligible claims, claimed claims,
  total capped first-claim delay, maximum capped first-claim delay, interactions,
  distinct apps. Counts are uint32, delays are uint64 and at most 30 days each
  (the board rejects a larger maximum), and distinct apps is uint16.
- One `TokenReport` per epoch token, in policy order: claimed, bought, sold,
  other out, reward held, reward sold, reward other out, balance. All are uint128.

The board recomputes all scores. It rejects zero/ineligible wallets, duplicates,
invalid accounting, impossible aggregate delays, increased scores, reversed
ties, overflow, token count mismatches and exceeded seat/wallet totals. The last
row of the previous batch participates in ordering checks. A failure reverts
the entire batch. Appending does not expose a draft as a published ranking.

`finalizeEpoch(epoch)` requires exactly the declared wallet count and activated
seat sum and an unexpired snapshot. It publishes atomically. `abortEpoch(epoch)`
is available to the owner or current reporter and never deletes published
history; the owner's `setReporter` also aborts a pending draft inline, so a
reporter rotation never waits on the reporter. Aborted draft storage remains on-chain but cannot be queried through
the published wallet/leaderboard APIs. An empty activated census can publish
with zero rows.

If upload fails, inspect `getEpoch` and receipts. Retry a reverted batch only
after confirming `walletsWritten`; a successful batch must not be resent. If
the draft expired or its observations were wrong, abort it and rescan. The
reference `prepare` command intentionally refuses to prepare a new publication
when a draft exists. It does not automatically resume, abort or overwrite one.
Only one reporter publication may be in flight at a time. Never splice calls
from different prepared packages.

The report hash uses the full canonical JSON report, including its policy,
counts, wallet rows and per-allocation evidence. `source_log_digest` is SHA-256
of the domain `IMDChadBoard-indexer-v1\n` followed by canonical deduplicated logs
plus newline, first the seat pass and then the activity pass, each in canonical
order. It is reproducible across block chunk sizes. The operator retains or
publishes the report and should retain receipts for challenges. Neither digest
is a Merkle proof, signature authorization or guarantee of correct data.
