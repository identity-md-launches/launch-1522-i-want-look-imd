/// <reference types="vite/client" />
import { getAddress, type Address } from "viem";
import type { Snapshot, WalletRow } from "./domain";
import { parseRadarObservation, type RadarObservation } from "./radar-data";

// Optional off-chain data service (service/ in this repository). The static site
// stays static: it only reads JSON from this read-only API. The base URL comes
// from the build (VITE_CHADBOARD_API) or a runtime override in the page hash
// (#api=https://host) remembered in localStorage. Empty means contract only.
const STORAGE_KEY = "chadboard.api";

export function feedBase(): string {
  try {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromHash = hash.get("api");
    if (fromHash !== null) {
      if (fromHash === "") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, fromHash);
    }
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored.replace(/\/+$/, "");
  } catch {
    // Storage may be unavailable; fall through to the build-time value.
  }
  const built = (import.meta.env.VITE_CHADBOARD_API as string | undefined) ?? "";
  return built.replace(/\/+$/, "");
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(12000) });
  const body = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(body.error ?? `Data service error ${response.status}`);
  return body;
}

type Feed = {
  snapshotId: string;
  epoch: string;
  block: string;
  timestamp: number;
  publishedAt: number;
  totalSeats: string;
  activatedSeats: string;
  wallets: number;
  stale: boolean;
  evidenceHash: `0x${string}`;
  scoreVersion: string;
  seatCensusAvailable?: boolean;
  source?: "ethereum" | "imd-radar" | "merged";
  sourceRetrievedAt?: number;
};

export async function loadFeed(): Promise<Snapshot | null> {
  const base = feedBase();
  if (!base) return null;
  const feed = await getJson<Feed>(`${base}/v1/site-feed`);
  return {
    epoch: feed.epoch,
    block: feed.block,
    timestamp: feed.timestamp,
    publishedAt: feed.publishedAt,
    totalSeats: feed.totalSeats,
    activatedSeats: feed.activatedSeats,
    wallets: feed.wallets,
    stale: feed.stale,
    currentConfiguration: true,
    reporter: null,
    evidenceHash: feed.evidenceHash,
    methodologyHash: null,
    source: "service",
    snapshotId: feed.snapshotId,
    seatCensusAvailable: feed.seatCensusAvailable,
    dataSource: feed.source,
    sourceRetrievedAt: feed.sourceRetrievedAt,
  };
}

type FeedWallet = {
  wallet: string;
  found: boolean;
  rank: number;
  score: number;
  tier: number;
  seat?: { count: number; status?: string };
  balances?: { current: { raw: string }; totalSent: { raw: string } };
  holding?: { retentionRatioBps: number };
  source?: "ethereum" | "imd-radar" | "merged";
  sourceRetrievedAt?: number;
  asOfBlock?: number;
  conflict?: boolean;
  radar?: RadarObservation;
};

function toRow(row: FeedWallet, token: Address): WalletRow {
  // Malformed optional enrichment never makes the Ethereum rows unavailable.
  let radar: RadarObservation | undefined;
  try { if (row.radar) radar = parseRadarObservation(row.radar); } catch { radar = undefined; }
  const provenance = { source: row.source, sourceRetrievedAt: row.sourceRetrievedAt, asOfBlock: row.asOfBlock,
    conflict: row.conflict, radar, seatStatus: row.seat?.status };
  if (!row.found)
    return { ...provenance, wallet: getAddress(row.wallet), found: false, rank: 0, score: 0, tier: 0, seats: 0 };
  return {
    ...provenance,
    wallet: getAddress(row.wallet),
    found: true,
    rank: row.rank,
    score: row.score,
    tier: row.tier,
    seats: row.seat?.count ?? 0,
    retentionBps: row.holding?.retentionRatioBps,
    tokens: row.balances
      ? [
          {
            token,
            symbol: "IMD",
            decimals: 18,
            claimed: "0",
            bought: "0",
            sold: "0",
            otherOut: row.balances.totalSent.raw,
            rewardHeld: "0",
            rewardSold: "0",
            rewardOtherOut: "0",
            balance: row.balances.current.raw,
          },
        ]
      : [],
  };
}

export async function feedLeaders(snapshotId: string, count: number, token: Address): Promise<WalletRow[]> {
  const body = await getJson<{ rows: FeedWallet[] }>(
    `${feedBase()}/v1/leaderboard?top=${count}&snapshot=${encodeURIComponent(snapshotId)}`,
  );
  return body.rows.map((row) => toRow(row, token));
}

export async function feedWallets(snapshotId: string, wallets: Address[], token: Address): Promise<WalletRow[]> {
  const body = await getJson<{ wallets: FeedWallet[] }>(
    `${feedBase()}/v1/wallets?addresses=${wallets.join(",")}&snapshot=${encodeURIComponent(snapshotId)}`,
  );
  return body.wallets.map((row) => toRow(row, token));
}
