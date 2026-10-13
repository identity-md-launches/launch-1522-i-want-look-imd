type Source = { sourceRetrievedAt: number | null; sourceUrl: string; responseId: number; responseHash: string; dataQuality: { stale: boolean } };
export type RadarObservation = {
  sourceRetrievedAt: number | null;
  seats: { seat: number; owner: string; agentId: number; status: string | null; online: boolean | null; accepted: number; rejected: number; failed: number; pending: number; latestWorkAt: number | null; responseId: number; sourceUrl: string; sourceRetrievedAt: number }[];
  relationships: { seat: number; owner: string }[];
  ethereumRelationships: { seat: string; wallet: string; active: number | null }[];
  launches: { wallet: string; participation: number[]; eligibleValueUsd: string; eligibleUnclaimedUsd: string; rewards: { launch: number; symbol: string; rewardTokens: string; unclaimedTokens: string }[]; excluded: { launch: number; reason: string }[] }[];
  sources: Source[];
  conflict: boolean;
  conflicts: { field: string; kind: string; seat?: number; ethereum?: string | boolean; radar?: string | string[]; note?: string }[];
  dataQuality: { available: boolean; stale: boolean; seatDetailsComplete: boolean };
};

/** Validate untrusted service/recovery data before it can render controls or links. */
export function parseRadarObservation(value: unknown): RadarObservation {
  const fail = (): never => { throw new Error("Malformed enrichment response. Ethereum rankings are unchanged."); };
  const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
  const list = (v: unknown): v is unknown[] => Array.isArray(v) && v.length <= 10000;
  const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
  const time = (v: unknown) => v === null || (count(v) && v < 8_640_000_000_000);
  const address = (v: unknown) => typeof v === "string" && /^0x[\da-f]{40}$/i.test(v);
  const text = (v: unknown): v is string => typeof v === "string" && v.length < 1000;
  const amount = (v: unknown) => text(v) && /^\d+(\.\d+)?$/.test(v) && Number.isFinite(Number(v));
  const url = (v: unknown) => text(v) && /^https:\/\/www\.imdradar\.site\/api\/(feed\?view=(swarm|seat&id=\d+)|launchpad\?view=agents)$/.test(v);
  if (!obj(value) || !obj(value.dataQuality) || !time(value.sourceRetrievedAt) || typeof value.conflict !== "boolean") return fail();
  for (const key of ["available", "stale", "seatDetailsComplete"]) if (typeof value.dataQuality[key] !== "boolean") return fail();
  for (const key of ["seats", "relationships", "ethereumRelationships", "launches", "sources", "conflicts"]) if (!list(value[key])) return fail();
  for (const s of value.seats as unknown[]) {
    if (!obj(s) || !address(s.owner) || !url(s.sourceUrl) || !time(s.sourceRetrievedAt) || !time(s.latestWorkAt) || (s.online !== null && typeof s.online !== "boolean") || (s.status !== null && !text(s.status))) return fail();
    for (const key of ["seat", "agentId", "accepted", "rejected", "failed", "pending", "responseId"]) if (!count(s[key])) return fail();
  }
  for (const r of value.relationships as unknown[]) if (!obj(r) || !count(r.seat) || !address(r.owner)) return fail();
  for (const r of value.ethereumRelationships as unknown[]) if (!obj(r) || !text(r.seat) || !/^\d+$/.test(r.seat) || !address(r.wallet) || ![null, 0, 1].includes(r.active as number | null)) return fail();
  for (const a of value.launches as unknown[]) {
    if (!obj(a) || !address(a.wallet) || !list(a.participation) || !a.participation.every(count) || !amount(a.eligibleValueUsd) || !amount(a.eligibleUnclaimedUsd) || !list(a.rewards) || !list(a.excluded)) return fail();
    for (const r of a.rewards) if (!obj(r) || !count(r.launch) || !text(r.symbol) || !amount(r.rewardTokens) || !amount(r.unclaimedTokens)) return fail();
    for (const r of a.excluded) if (!obj(r) || !count(r.launch) || !text(r.reason)) return fail();
  }
  for (const s of value.sources as unknown[]) if (!obj(s) || !url(s.sourceUrl) || !count(s.responseId) || !time(s.sourceRetrievedAt) || !text(s.responseHash) || !/^[\da-f]{64}$/.test(s.responseHash) || !obj(s.dataQuality) || typeof s.dataQuality.stale !== "boolean") return fail();
  for (const c of value.conflicts as unknown[]) {
    if (!obj(c) || !text(c.field) || !text(c.kind) || (c.seat !== undefined && !count(c.seat)) || (c.note !== undefined && !text(c.note))) return fail();
    if (c.ethereum !== undefined && typeof c.ethereum !== "boolean" && !text(c.ethereum)) return fail();
    if (c.radar !== undefined && !text(c.radar) && !(list(c.radar) && c.radar.every(text))) return fail();
  }
  return value as unknown as RadarObservation;
}
