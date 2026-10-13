import {
  createPublicClient,
  createWalletClient,
  custom,
  decodeEventLog,
  encodeFunctionData,
  erc20Abi,
  fallback,
  getAddress,
  http,
  keccak256,
  type Address,
  type EIP1193Provider,
  type Hex,
  type TransactionReceipt,
} from "viem";
import { mainnet } from "viem/chains";
import { boardAbi } from "./board-abi";
import { feedLeaders, feedWallets, loadFeed } from "./feed";
import {
  BOARD,
  BOARD_RUNTIME_HASH,
  BURN,
  CHAIN_ID,
  IMD,
  RPC_URLS,
} from "./config";
import {
  queryAmount,
  type BoardStatus,
  type PaymentRecord,
  type Query,
  type Report,
  type TokenObservation,
  type WalletRow,
} from "./domain";

export const client = createPublicClient({
  chain: mainnet,
  transport: fallback(
    RPC_URLS.map((url) => http(url, { timeout: 12_000, retryCount: 1 })),
  ),
  batch: { multicall: false },
});

async function verifyContracts(blockNumber: bigint) {
  const [chainId, boardCode, tokenCode, decimals] = await Promise.all([
    client.getChainId(),
    client.getCode({ address: BOARD, blockNumber }),
    client.getCode({ address: IMD, blockNumber }),
    client.readContract({
      address: IMD,
      abi: erc20Abi,
      functionName: "decimals",
      blockNumber,
    }),
  ]);
  if (chainId !== CHAIN_ID)
    throw new Error(
      "The RPC returned a different network. Payments are paused. Refresh to retry.",
    );
  if (!boardCode || keccak256(boardCode) !== BOARD_RUNTIME_HASH)
    throw new Error(
      "The board code could not be verified. Payments are paused. Refresh to retry.",
    );
  if (!tokenCode || tokenCode === "0x" || decimals !== 18)
    throw new Error(
      "The IMD token could not be verified. Payments are paused. Refresh to retry.",
    );
}

export async function loadBoard(): Promise<BoardStatus> {
  const blockNumber = await client.getBlockNumber({ cacheTime: 0 });
  await verifyContracts(blockNumber);
  const epoch = await client.readContract({
    address: BOARD,
    abi: boardAbi,
    functionName: "latestEpoch",
    blockNumber,
  });
  if (epoch === 0n) {
    // No on-chain epoch yet: fall back to the data service snapshot when one is configured.
    const feed = await loadFeed().catch(() => null);
    return feed ? { kind: "ready", snapshot: feed } : { kind: "empty" };
  }
  const [data, stale, currentConfiguration] = await client.readContract({
    address: BOARD,
    abi: boardAbi,
    functionName: "summary",
    blockNumber,
  });
  return {
    kind: "ready",
    snapshot: {
      epoch: epoch.toString(),
      block: data.snapshot.blockNumber.toString(),
      timestamp: Number(data.snapshot.timestamp),
      publishedAt: Number(data.publishedAt),
      totalSeats: data.snapshot.totalSeats.toString(),
      activatedSeats: data.snapshot.activatedSeats.toString(),
      wallets: data.walletsWritten,
      stale,
      currentConfiguration,
      reporter: data.reporter,
      evidenceHash: data.snapshot.evidenceHash,
      methodologyHash: data.methodologyHash,
      source: "chain",
    },
  };
}

export async function prepareQuery(
  query: Query,
  onProgress: (message: string) => void,
): Promise<Report> {
  const status = await loadBoard();
  if (status.kind !== "ready")
    throw new Error(
      "No snapshot has been published yet. Payments are paused. Check again after the board operator publishes one.",
    );
  const snapshot = status.snapshot;
  if (snapshot.stale || !snapshot.currentConfiguration)
    throw new Error(
      "The latest snapshot is out of date. Payments are paused until the operator publishes a current snapshot.",
    );
  if (!snapshot.wallets)
    throw new Error(
      "This snapshot has no ranked wallets. No payment is needed. Check again after a new snapshot is published.",
    );
  const rows: WalletRow[] = [];
  if (snapshot.source === "service" && snapshot.snapshotId) {
    onProgress("Reading the data service snapshot…");
    rows.push(
      ...(query.kind === "leaders"
        ? await feedLeaders(snapshot.snapshotId, query.count, IMD)
        : await feedWallets(snapshot.snapshotId, query.wallets, IMD)),
    );
    if (!rows.some((row) => row.found))
      throw new Error(
        "None of these wallets is in the latest snapshot. No payment is needed.",
      );
    return { query, snapshot, rows, createdAt: Date.now() };
  }
  const epoch = BigInt(snapshot.epoch);
  if (query.kind === "leaders") {
    const count = Math.min(query.count, snapshot.wallets);
    for (let offset = 0; offset < count; offset += 100) {
      onProgress(
        `Reading rankings ${offset + 1}–${Math.min(offset + 100, count)}…`,
      );
      const page = await client.readContract({
        address: BOARD,
        abi: boardAbi,
        functionName: "leaderboard",
        args: [epoch, offset, Math.min(100, count - offset)],
      });
      for (const row of page)
        rows.push({
          wallet: row.wallet,
          found: true,
          rank: row.rank,
          score: row.score,
          tier: row.tier,
          seats: row.activeSeats,
        });
    }
  } else {
    const policies = await client.readContract({
      address: BOARD,
      abi: boardAbi,
      functionName: "epochTokenPolicies",
      args: [epoch],
    });
    const metadata = await Promise.all(
      policies.map(async (p) => {
        try {
          const [symbol, decimals] = await Promise.all([
            client.readContract({
              address: p.token,
              abi: erc20Abi,
              functionName: "symbol",
            }),
            client.readContract({
              address: p.token,
              abi: erc20Abi,
              functionName: "decimals",
            }),
          ]);
          return { token: p.token, symbol: symbol.slice(0, 32), decimals };
        } catch {
          return { token: p.token, symbol: "Token", decimals: null };
        }
      }),
    );
    // Bounded parallel reads, all pinned to one immutable epoch.
    for (let i = 0; i < query.wallets.length; i += 5) {
      onProgress(
        `Checking wallets ${i + 1}–${Math.min(i + 5, query.wallets.length)}…`,
      );
      const chunk = await Promise.all(
        query.wallets.slice(i, i + 5).map(async (wallet) => {
          const [rating, tokens] = await Promise.all([
            client.readContract({
              address: BOARD,
              abi: boardAbi,
              functionName: "walletAt",
              args: [epoch, wallet],
            }),
            client.readContract({
              address: BOARD,
              abi: boardAbi,
              functionName: "walletTokens",
              args: [epoch, wallet],
            }),
          ]);
          const { stats } = rating;
          const observations: TokenObservation[] = tokens.map((t, index) => ({
            ...metadata[index],
            claimed: t.claimed.toString(),
            bought: t.bought.toString(),
            sold: t.sold.toString(),
            otherOut: t.otherOut.toString(),
            rewardHeld: t.rewardHeld.toString(),
            rewardSold: t.rewardSold.toString(),
            rewardOtherOut: t.rewardOtherOut.toString(),
            balance: t.balance.toString(),
          }));
          return {
            wallet,
            found: rating.found,
            rank: stats.rank,
            score: stats.score,
            tier: rating.tier,
            seats: stats.metrics.activeSeats,
            launches: stats.metrics.launches,
            eligibleClaims: stats.metrics.eligibleClaims,
            claimedClaims: stats.metrics.claimedClaims,
            totalClaimDelay: stats.metrics.totalClaimDelay.toString(),
            maxClaimDelay: stats.metrics.maxClaimDelay.toString(),
            apps: stats.metrics.distinctApps,
            interactions: stats.metrics.interactions,
            retentionBps: stats.retentionBps,
            supportBps: stats.supportBps,
            tokens: observations,
          };
        }),
      );
      rows.push(...chunk);
    }
  }
  if (!rows.some((row) => row.found))
    throw new Error(
      "None of these wallets is in the latest snapshot. No payment is needed. Only wallets associated with activated IMD seats are ranked.",
    );
  return { query, snapshot, rows, createdAt: Date.now() };
}

export async function connect(provider: EIP1193Provider): Promise<Address> {
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!accounts[0])
    throw new Error(
      "The wallet did not share an account. Open your wallet and try connecting again.",
    );
  return getAddress(accounts[0]);
}
export async function switchNetwork(provider: EIP1193Provider) {
  await provider.request({
    method: "wallet_switchEthereumChain",
    params: [{ chainId: "0x1" }],
  });
}
export async function sendPayment(
  provider: EIP1193Provider,
  account: Address,
  report: Report,
): Promise<Hex> {
  const [chainId, accounts, status] = await Promise.all([
    provider.request({ method: "eth_chainId" }),
    provider.request({ method: "eth_accounts" }),
    loadBoard(),
  ]);
  if (Number(chainId) !== CHAIN_ID)
    throw new Error("Switch your wallet to Ethereum before sending IMD.");
  if (!accounts[0] || getAddress(accounts[0]) !== getAddress(account))
    throw new Error(
      "Your wallet account changed. Reconnect and review the query again.",
    );
  if (
    status.kind !== "ready" ||
    status.snapshot.stale ||
    !status.snapshot.currentConfiguration ||
    status.snapshot.epoch !== report.snapshot.epoch
    || status.snapshot.source !== report.snapshot.source
    || status.snapshot.snapshotId !== report.snapshot.snapshotId
    || status.snapshot.block !== report.snapshot.block
    || status.snapshot.evidenceHash !== report.snapshot.evidenceHash
  )
    throw new Error(
      "The snapshot changed or is no longer current. Close this review and check your query again. No payment was sent.",
    );
  const amount = queryAmount(report.query);
  const balance = await client.readContract({
    address: IMD,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: [account],
  });
  if (balance < amount)
    throw new Error(
      "Your wallet has insufficient IMD for this query. Add IMD, then try again. You also need ETH for network fees.",
    );
  const simulated = await client.simulateContract({
    address: IMD,
    abi: erc20Abi,
    functionName: "transfer",
    args: [BURN, amount],
    account,
  });
  if (!simulated.result)
    throw new Error(
      "IMD rejected the transfer simulation. No payment was sent.",
    );
  const wallet = createWalletClient({
    account,
    chain: mainnet,
    transport: custom(provider),
  });
  // Exact-value ERC-20 transfer: no approvals, signatures, routers or intermediary custody.
  return wallet.sendTransaction({
    account,
    to: IMD,
    data: encodeFunctionData({
      abi: erc20Abi,
      functionName: "transfer",
      args: [BURN, amount],
    }),
    value: 0n,
    chain: mainnet,
  });
}

export function verifyReceipt(
  record: PaymentRecord,
  receipt: TransactionReceipt,
): void {
  if (receipt.status !== "success")
    throw new Error(
      "The payment reverted. No IMD was transferred; Ethereum gas may have been spent. Start a new query to try again.",
    );
  if (receipt.transactionHash.toLowerCase() !== record.hash.toLowerCase())
    throw new Error(
      "The receipt does not match this payment. Keep the transaction hash and check again.",
    );
  if (
    receipt.from.toLowerCase() !== record.account.toLowerCase() ||
    receipt.to?.toLowerCase() !== IMD.toLowerCase()
  )
    throw new Error(
      "The receipt does not match the paying wallet and IMD token.",
    );
  const amount = queryAmount(record.report.query);
  const paid = receipt.logs.some((log) => {
    if (log.address.toLowerCase() !== IMD.toLowerCase()) return false;
    try {
      const event = decodeEventLog({
        abi: erc20Abi,
        eventName: "Transfer",
        data: log.data,
        topics: log.topics,
      });
      return (
        event.args.from.toLowerCase() === record.account.toLowerCase() &&
        event.args.to.toLowerCase() === BURN.toLowerCase() &&
        event.args.value === amount
      );
    } catch {
      return false;
    }
  });
  if (!paid)
    throw new Error(
      "No matching IMD transfer to the dead address was found. Keep this transaction hash for verification.",
    );
}
export async function confirmPayment(record: PaymentRecord) {
  const receipt = await client.waitForTransactionReceipt({
    hash: record.hash,
    confirmations: 2,
    timeout: 90_000,
    pollingInterval: 4_000,
    onReplaced: () => {
      /* A different hash must be reviewed, never silently accepted. */
    },
  });
  verifyReceipt(record, receipt);
}
