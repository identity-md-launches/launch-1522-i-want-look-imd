# Security and operational review

This project is informational. Its only production contract is `IMDChadBoard`.
It neither transfers tokens nor accepts ordinary ETH transfers, has no approvals,
fallback execution, signature recovery, delegatecall, proxy or upgrade power.
Forced ETH or accidentally sent ERC-20s cannot be recovered. Do not send funds
to the board. Rankings must not be used as a payout/credit oracle without a
separate threat model and independent review.

## Trust boundaries

| Party / input | Power and limitation |
| --- | --- |
| Owner | Configures source/policy, reporter, token thresholds and freshness. Can abort drafts and transfer ownership with acceptance. Cannot rewrite published records or change the score formula. A compromised owner can appoint a dishonest reporter; changes are visible but not prevented by a timelock. |
| Reporter | Attests complete censuses, historical activity and balances. Can omit wallets, invent structurally consistent observations or censor new reports. Contract validation cannot prove the event history. No reporter-held funds or user approvals are required. |
| RPC and source contracts | Indexer trusts RPC completeness and authentic event semantics. It verifies canonical block hashes and pins balance reads, but a malicious RPC could fabricate a consistent response set. Source contracts that allow spoofed wallet fields undermine attribution. |
| Policy | Selects time window, tokens, thresholds, association semantics and recognized event sources. Excluding a venue reduces sale coverage. A changed policy invalidates freshness of older snapshots; it does not retroactively re-score them. |
| Consumer | Must check observation time, current configuration, `found`, evidence and data availability. Rank zero means absent. “Other out” is unresolved disposition, not proof of continued holding or a sale. |

## Review and regression cases

- Every write path was checked for its caller boundary. Factory caller and
  nominated owner are distinct in tests. Reporters cannot configure the board;
  owners must explicitly nominate themselves if they also operate reporting.
  Revocation is an explicit zero-reporter state with `NotConfigured` failures.
- Constructors take one explicit owner and make no dependency calls. Runtime
  opcode inspection and EIP-170/EIP-3860 size checks reproduce the supplied
  deployment floor locally without its environment-driven harness.
- There are no state-changing external calls in the production contract, so no
  reentrant token hooks, Ether callbacks or untrusted delegate execution. Code
  presence is checked at first publication, not in the constructor.
- A concrete configuration race was prevented: a previously prepared report
  cannot begin after the owner changes policy/token order because the input
  carries an expected configuration revision. Configuration is also frozen
  during a draft. Old epoch policies and scores are copied and remain immutable.
- Drafts do not replace `latestEpoch`. Partial uploads, expired drafts, failed
  batches, duplicates and seat total mismatches cannot publish. The owner can
  abort a stalled draft without the reporter's cooperation.
- Wallet ranks are assigned while validating both score and address ordering
  across batch boundaries. The reporter cannot choose arbitrary rank numbers.
  Read cost is bounded by a requested page; global rank does not scan wallets.
- Reward sums widen to uint256 before addition/multiplication. Score components
  are capped, token ratios normalize decimals, and fuzz tests check score bounds
  and nonincreasing scores under further reward disposal. There are no prices,
  market oracles, randomness or payout rounding to exploit.
- A concrete ambiguous-provenance case was found during local review: a gift
  and reward payment from the same source for the same amount in one transaction
  could cause a naive matcher to choose the gift and mislabel an intervening
  disposal as a reward sale. The scanner now rejects multiple matching transfers;
  a regression test covers that exact sequence.
- Recognized event/Transfer pairing is unique per transaction and requires exact
  amounts and counterparties. Missing transfers, overclaims, duplicate allocation
  IDs, malformed addresses, removed/conflicting logs and wrong-chain responses
  fail closed. Self transfers and gifts do not farm purchased/held reward units.
- Recent block hashes are checked on-chain; old hashes and all timestamp/metric
  attestations remain a trust assumption. The indexer requires finalized reads
  and rechecks the block. Snapshot freshness is information for readers, not a
  hard prohibition on accessing old immutable results.

The full-sized batch test exercises 20 wallets and 16 token reports each. Batches
can still be expensive; operators should estimate gas and use smaller batches.
Each epoch uses permanent storage. The operator funds these publications; users
cannot grow state through unrestricted writes. A large census increases total
publication cost but does not increase a single-wallet read's asymptotic cost.

## Outstanding operational review

Before publishing real rankings, the owner/operator must verify actual IMD
contracts, token properties, beneficiary/activation semantics, start block,
event namespaces and venue/app attribution. The generic event decoder must not
be treated as a universal DEX or ABI decoder. Review actual adapters separately.
Publish the methodology and support thresholds so readers can interpret the
score's incentives. Protect the reporting signer and monitor stale snapshots.

Gross buys, prompt partial claims, capped initiation counts and distinct app
usage are gameable heuristics. There is no financial settlement, wash-trade
filter, Sybil identity proof, claim eligibility proof or off-chain browsing
telemetry. Off-chain provenance assumptions and trust are deliberate and visible.

Local tools run: Solidity compilation, Foundry unit/fuzz tests, formatting,
runtime opcode/size tests, Python semantic/RPC failure tests, and a real local
Anvil end-to-end test. Slither, Mythril and a separate independent contributor
audit were not run. Passing these checks does not replace an independent review
of the contracts and the eventual mainnet source configuration.
