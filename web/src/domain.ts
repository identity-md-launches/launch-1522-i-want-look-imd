import {
  getAddress,
  isAddress,
  parseUnits,
  type Address,
  type Hex,
} from "viem";

export const PACKS = [
  { count: 10, price: "0.1", detail: "A quick look" },
  { count: 50, price: "0.5", detail: "The front runners" },
  { count: 100, price: "1", detail: "A wider view" },
  { count: 1000, price: "2", detail: "The full picture" },
] as const;
export type PackSize = (typeof PACKS)[number]["count"];
export type Query =
  | { kind: "wallets"; wallets: Address[] }
  | { kind: "leaders"; count: PackSize };
export type Snapshot = {
  epoch: string;
  block: string;
  timestamp: number;
  publishedAt: number;
  totalSeats: string;
  activatedSeats: string;
  wallets: number;
  stale: boolean;
  currentConfiguration: boolean;
  reporter: Address;
  evidenceHash: Hex;
  methodologyHash: Hex;
  // "service" rows come from the read-only data service feed while the board
  // has no published epoch; "chain" rows come from the IMDChadBoard contract.
  source?: "chain" | "service";
  snapshotId?: string;
};
export type BoardStatus =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "ready"; snapshot: Snapshot };
export type TokenObservation = {
  token: Address;
  symbol: string;
  decimals: number | null;
  claimed: string;
  bought: string;
  sold: string;
  otherOut: string;
  rewardHeld: string;
  rewardSold: string;
  rewardOtherOut: string;
  balance: string;
};
export type WalletRow = {
  wallet: Address;
  found: boolean;
  rank: number;
  score: number;
  tier: number;
  seats: number;
  launches?: number;
  eligibleClaims?: number;
  claimedClaims?: number;
  totalClaimDelay?: string;
  maxClaimDelay?: string;
  apps?: number;
  interactions?: number;
  retentionBps?: number;
  supportBps?: number;
  tokens?: TokenObservation[];
};
export type Report = {
  query: Query;
  snapshot: Snapshot;
  rows: WalletRow[];
  createdAt: number;
};
export type PaymentRecord = {
  hash: Hex;
  account: Address;
  report: Report;
  amount: string;
};
export const TIERS = ["Observer", "Contributor", "Chad", "GigaChad"];

export function parseWallets(input: string): Address[] {
  const parts = input
    .trim()
    .split(/[\s,;]+/)
    .filter(Boolean);
  if (!parts.length)
    throw new Error("Enter at least one Ethereum wallet address.");
  for (const part of parts) {
    if (!isAddress(part, { strict: true }))
      throw new Error(
        `Check this address: ${part.slice(0, 80)}. Use a full 42-character Ethereum address with a valid checksum or all lowercase.`,
      );
  }
  const wallets = [...new Set(parts.map((part) => getAddress(part)))];
  if (wallets.length > 100)
    throw new Error(
      "Query up to 100 unique wallets at a time. Split this list into smaller batches.",
    );
  return wallets;
}
export function queryPrice(query: Query): string {
  if (query.kind === "wallets") return (query.wallets.length / 10).toFixed(1);
  const pack = PACKS.find((p) => p.count === query.count);
  if (!pack) throw new Error("Choose one of the available leaderboard sizes.");
  return pack.price;
}
export function queryAmount(query: Query): bigint {
  return parseUnits(queryPrice(query), 18);
}
export function queryLabel(query: Query): string {
  return query.kind === "leaders"
    ? `Top ${query.count.toLocaleString()}`
    : `${query.wallets.length} wallet${query.wallets.length === 1 ? "" : "s"}`;
}
export function errorMessage(error: unknown): string {
  const e = error as {
    code?: number;
    shortMessage?: string;
    message?: string;
    cause?: { code?: number };
  };
  if (
    e?.code === 4001 ||
    e?.cause?.code === 4001 ||
    /user rejected|user denied/i.test(e?.message ?? "")
  )
    return "You declined the wallet request. No new payment was sent. Try again when you are ready.";
  return (
    e?.shortMessage ||
    e?.message ||
    "The request failed. Check your connection and try again."
  );
}
export function formatDelay(seconds: string | undefined, divisor = 1): string {
  if (!seconds || divisor === 0) return "No claims";
  const value = Number(seconds) / divisor;
  if (value < 60) return `${Math.round(value)} sec`;
  if (value < 3600) return `${(value / 60).toFixed(1)} min`;
  if (value < 86400) return `${(value / 3600).toFixed(1)} hr`;
  return `${(value / 86400).toFixed(1)} days`;
}

/** Validate locally saved recovery data before any rendering or receipt lookup. */
export function decodeRecovery(text: string): PaymentRecord {
  const invalid = () => {
    throw new Error(
      "This is not a valid ChadBoard recovery file. Choose the JSON file saved from a pending payment.",
    );
  };
  if (text.length > 2_000_000) return invalid();
  let value: PaymentRecord;
  try {
    value = JSON.parse(text) as PaymentRecord;
  } catch {
    return invalid();
  }
  const address = (v: unknown) =>
    typeof v === "string" && isAddress(v, { strict: false });
  const hash = (v: unknown) =>
    typeof v === "string" && /^0x[\da-fA-F]{64}$/.test(v);
  const integer = (v: unknown) =>
    typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
  const digits = (v: unknown) => typeof v === "string" && /^\d{1,78}$/.test(v);
  if (!value || !hash(value.hash) || !address(value.account) || !value.report)
    return invalid();
  const { query, snapshot, rows, createdAt } = value.report;
  if (!query) return invalid();
  if (query.kind === "wallets") {
    if (
      !Array.isArray(query.wallets) ||
      query.wallets.length < 1 ||
      query.wallets.length > 100 ||
      !query.wallets.every(address)
    )
      return invalid();
    if (
      new Set(query.wallets.map((w) => w.toLowerCase())).size !==
      query.wallets.length
    )
      return invalid();
  } else if (
    query.kind !== "leaders" ||
    !PACKS.some((pack) => pack.count === query.count)
  )
    return invalid();
  if (value.amount !== queryPrice(query) || !integer(createdAt))
    return invalid();
  if (
    !snapshot ||
    !digits(snapshot.epoch) ||
    BigInt(snapshot.epoch) === 0n ||
    !digits(snapshot.block) ||
    !integer(snapshot.timestamp) ||
    snapshot.timestamp > 8_640_000_000_000 ||
    !integer(snapshot.publishedAt) ||
    !digits(snapshot.totalSeats) ||
    !digits(snapshot.activatedSeats) ||
    !integer(snapshot.wallets) ||
    !address(snapshot.reporter) ||
    !hash(snapshot.evidenceHash) ||
    !hash(snapshot.methodologyHash) ||
    typeof snapshot.stale !== "boolean" ||
    typeof snapshot.currentConfiguration !== "boolean"
  )
    return invalid();
  if (
    !Array.isArray(rows) ||
    rows.length < 1 ||
    rows.length >
      (query.kind === "wallets" ? query.wallets.length : query.count)
  )
    return invalid();
  for (const row of rows) {
    if (
      !row ||
      !address(row.wallet) ||
      typeof row.found !== "boolean" ||
      !integer(row.rank) ||
      !integer(row.seats) ||
      !integer(row.score) ||
      row.score > 10000 ||
      !integer(row.tier) ||
      row.tier > 3
    )
      return invalid();
    for (const key of [
      "launches",
      "eligibleClaims",
      "claimedClaims",
      "apps",
      "interactions",
      "retentionBps",
      "supportBps",
    ] as const) {
      if (row[key] !== undefined && !integer(row[key])) return invalid();
    }
    for (const key of ["totalClaimDelay", "maxClaimDelay"] as const)
      if (row[key] !== undefined && !digits(row[key])) return invalid();
    if (row.tokens !== undefined) {
      if (!Array.isArray(row.tokens) || row.tokens.length > 16)
        return invalid();
      for (const token of row.tokens) {
        if (
          !token ||
          !address(token.token) ||
          typeof token.symbol !== "string" ||
          token.symbol.length > 32 ||
          (token.decimals !== null &&
            (!integer(token.decimals) || token.decimals > 255))
        )
          return invalid();
        for (const key of [
          "claimed",
          "bought",
          "sold",
          "otherOut",
          "rewardHeld",
          "rewardSold",
          "rewardOtherOut",
          "balance",
        ] as const)
          if (!digits(token[key])) return invalid();
      }
    }
  }
  return value;
}
