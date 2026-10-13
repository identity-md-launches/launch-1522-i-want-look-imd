import { useRef, useState } from "react";
import { feedBase } from "./feed";

import { parseRadarObservation, type RadarObservation } from "./radar-data";
type RadarStatus = {
  enabled: boolean; cachedResponses: number; sourceRetrievedAt: number | null;
  dataQuality: { status: string; staleResponses: number };
};
export async function radarJson<T>(path: string): Promise<T> {
  const base = feedBase();
  if (!base) throw new Error("Connect a data service to view optional Radar observations.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${base}${path}`, { signal: controller.signal, headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("Enrichment is unavailable. Retry when the data service is reachable.");
    return await response.json() as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw new Error("The data service timed out. Try again.");
    throw error;
  } finally { clearTimeout(timer); }
}
const observedAt = (t: number | null) => t ? new Date(t * 1000).toLocaleString() : "Not available";

export function RadarDetails({ data }: { data: RadarObservation }) {
  return <div className="radar-details">
    <p className="small muted">IMD Radar enrichment · Retrieved {observedAt(data.sourceRetrievedAt)}. These observations do not affect scores, ranks or IMD accounting.</p>
    {!data.dataQuality.available && <p role="status">No cached Radar observations for this lookup. Ethereum queries remain available.</p>}
    {data.dataQuality.stale && <p className="source-warning">Stale Radar data. Check the retrieval and source times before using these observations.</p>}
    {data.conflict && <div className="source-warning"><strong>Sources disagree</strong><p>Ethereum at the snapshot block takes precedence. Both observations are preserved below.</p>
      <ul>{data.conflicts.map((c, i) => <li key={i}>Seat {c.seat ?? "unknown"}: {c.kind.replaceAll("-", " ")}.
        {c.ethereum !== undefined && <> Ethereum: <span className="address">{String(c.ethereum)}</span>.</>}
        {c.radar !== undefined && <> Radar: <span className="address">{Array.isArray(c.radar) ? c.radar.join(", ") : c.radar}</span>.</>}
        {c.note && <> {c.note}</>}
      </li>)}</ul></div>}
    {data.ethereumRelationships.length > 0 && <div><h3>Ethereum seat ownership</h3><ul className="source-list">{data.ethereumRelationships.map(r => <li key={r.seat}>Seat {r.seat} · <span className="address">{r.wallet}</span> · {r.active === null ? "Activation unknown" : r.active ? "Activated" : "Not activated"}</li>)}</ul></div>}
    {data.seats.length > 0 && <div><h3>Radar seat observations</h3><ul className="source-list">{data.seats.map((s, i) => <li key={`${s.responseId}-${s.seat}-${i}`}>
      <strong>Seat {s.seat} · Agent {s.agentId}</strong><p className="small muted">{s.sourceUrl.includes("view=seat") ? "Seat detail" : "Swarm summary"} · Retrieved {observedAt(s.sourceRetrievedAt)}</p><p className="address">{s.owner}</p>
      <p className="small">{s.status ?? "Status not reported"} · {s.online === null ? "Online state not reported" : s.online ? "Online" : "Offline"}</p>
      <p className="small">{s.accepted} accepted · {s.rejected} rejected · {s.failed} failed · {s.pending} pending</p>
      <p className="small muted">Latest work: {observedAt(s.latestWorkAt)}</p>
    </li>)}</ul></div>}
    {data.launches.map((a, i) => <div key={`${a.wallet}-${i}`}><h3>Radar launch estimates</h3>
      <p className="address small">{a.wallet}</p>
      <p>{a.participation.length} launches reported. Eligible rewards: ${Number(a.eligibleValueUsd).toFixed(2)}; unclaimed: ${Number(a.eligibleUnclaimedUsd).toFixed(2)}.</p>
      <p className="small muted">Low or unverified liquidity excludes {a.excluded.length} launches from these estimates. Participation is retained. Claimed rewards do not prove a sale or continued holding.</p>
      <details><summary>View launch participation and rewards</summary><p className="small source-wrap">Launches: {a.participation.join(", ") || "None reported"}</p>
        <ul>{a.rewards.map(r => <li key={r.launch}>Launch {r.launch} ({r.symbol}): {r.rewardTokens} tokens; {r.unclaimedTokens} unclaimed.</li>)}</ul>
        {a.excluded.length > 0 && <p className="small source-wrap">Excluded from value estimates: {a.excluded.map(r => r.launch).join(", ")}.</p>}
      </details>
    </div>)}
    {data.sources.length > 0 && <details><summary>View Radar source evidence</summary><ul className="source-list">{data.sources.map(s => <li key={s.responseId}>
      <a className="source-wrap" href={s.sourceUrl} target="_blank" rel="noreferrer">{s.sourceUrl}</a>
      <p className="small">Retrieved {observedAt(s.sourceRetrievedAt)}{s.dataQuality.stale ? " · Stale" : ""}</p>
      <p className="address small">SHA-256: {s.responseHash}</p>
      {feedBase() && <a href={`${feedBase()}/v1/radar/raw/${s.responseId}`} target="_blank" rel="noreferrer">Open stored response {s.responseId}</a>}
    </li>)}</ul></details>}
  </div>;
}

export function RadarPanel() {
  const [status, setStatus] = useState<RadarStatus | null>(null);
  const [data, setData] = useState<RadarObservation | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [lookup, setLookup] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [apiUrl, setApiUrl] = useState(feedBase);
  const input = useRef<HTMLInputElement>(null);
  async function refresh() {
    if (!feedBase()) return;
    try {
      const result = await radarJson<RadarStatus>("/v1/radar/status");
      if (!result?.dataQuality || typeof result.enabled !== "boolean" || typeof result.dataQuality.status !== "string" || !Number.isSafeInteger(result.cachedResponses) || !Number.isSafeInteger(result.dataQuality.staleResponses)) throw new Error("Malformed status");
      setStatus(result); setMessage("");
    }
    catch { setMessage("Radar enrichment is unavailable. Ethereum ranking queries still work. Use Refresh enrichment to retry."); }
  }
  async function search(event: React.FormEvent) {
    event.preventDefault();
    const value = lookup.trim();
    if (!/^\d{1,10}$/.test(value) && !/^0x[\da-fA-F]{40}$/.test(value)) {
      setInvalid(true); setMessage("Enter a seat number or a full Ethereum wallet address."); input.current?.focus(); return;
    }
    setInvalid(false); setBusy(true); setMessage("Loading cached enrichment…"); setData(null);
    try {
      const query = /^\d+$/.test(value) ? `seat=${value}` : `wallet=${value}`;
      const result = parseRadarObservation(await radarJson<unknown>(`/v1/radar/seats?${query}`));
      setData(result); setMessage(result.dataQuality.available ? "Cached observations loaded." : "No cached observations found.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Enrichment could not load. Try again."); }
    finally { setBusy(false); }
  }
  return <details className="source-panel" onToggle={e => { if (e.currentTarget.open) void refresh(); }}>
    <summary>Data sources · Ethereum rankings</summary>
    <p>Ethereum contract state and event history determine rankings. Optional IMD Radar data adds seat activity and launch context.</p>
    <p className="small muted">Radar never determines your score, snapshot order, IMD balance or whether tokens were sold or held.</p>
    {status && <p className="small">Radar: {status.enabled ? status.dataQuality.status : "disabled"} · {status.cachedResponses} cached responses · {status.dataQuality.staleResponses} stale. Last retrieved {observedAt(status.sourceRetrievedAt)}.</p>}
    {!feedBase() && <p className="small">Radar enrichment is not connected. You can use Ethereum queries independently.</p>}
    <form onSubmit={search} className="source-form">
      <label htmlFor="radar-lookup">Seat number or wallet address</label>
      <div className="source-controls"><input ref={input} id="radar-lookup" value={lookup} onChange={e => { setLookup(e.target.value); setInvalid(false); }} placeholder="Seat number or 0x address" aria-invalid={invalid} aria-describedby="radar-message" spellCheck={false} autoComplete="off" />
      <button className="button secondary" disabled={busy || !feedBase()}>{busy ? "Looking up…" : "Look up enrichment"}</button></div>
    </form>
    <p id="radar-message" role="status" className="small">{message}</p>
    {feedBase() && <button type="button" className="button secondary" onClick={() => void refresh()}>Refresh enrichment</button>}
    {data && <RadarDetails data={data} />}
    <details className="service-setting"><summary>Connect a data service</summary>
      <p className="small">Use a ChadBoard service you trust. Queries share the entered public address or seat number with that service.</p>
      <form onSubmit={e => {
        e.preventDefault();
        try {
          const url = new URL(apiUrl);
          if ((url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) || url.username || url.password || url.search || url.hash) throw new Error();
          localStorage.setItem("chadboard.api", url.href.replace(/\/$/, ""));
          window.location.hash = new URLSearchParams({ api: url.href.replace(/\/$/, "") }).toString();
          window.location.reload();
        } catch { setMessage("Use an HTTPS service URL without credentials, query parameters or a fragment. Localhost HTTP is supported for development."); }
      }}>
        <label htmlFor="radar-service">Data service URL</label><div className="source-controls"><input id="radar-service" type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} required placeholder="https://your-service.example" /><button className="button secondary">Connect service</button></div>
      </form>
      {feedBase() && <button type="button" className="text-button" onClick={() => { localStorage.removeItem("chadboard.api"); window.location.hash = "api="; window.location.reload(); }}>Disconnect service</button>}
    </details>
  </details>;
}
