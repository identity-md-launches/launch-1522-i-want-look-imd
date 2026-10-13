import { useState } from "react";
import { formatUnits } from "viem";
import { EXPLORER } from "./config";
import {
  formatDelay,
  queryLabel,
  TIERS,
  type PaymentRecord,
  type TokenObservation,
  type WalletRow,
} from "./domain";

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function units(value: string, token: TokenObservation) {
  return token.decimals === null
    ? `${value} raw units`
    : `${formatUnits(BigInt(value), token.decimals)} ${token.symbol}`;
}
function WalletDetail({ row }: { row: WalletRow }) {
  return (
    <details className="wallet-detail">
      <summary>View wallet activity</summary>
      <dl className="metric-grid">
        <div>
          <dt>Launches initiated</dt>
          <dd>{row.launches}</dd>
        </div>
        <div>
          <dt>Claims completed</dt>
          <dd>
            {row.claimedClaims} / {row.eligibleClaims}
          </dd>
        </div>
        <div>
          <dt>Average claim delay</dt>
          <dd>{formatDelay(row.totalClaimDelay, row.claimedClaims)}</dd>
        </div>
        <div>
          <dt>Longest claim delay</dt>
          <dd>{formatDelay(row.maxClaimDelay, row.claimedClaims ? 1 : 0)}</dd>
        </div>
        <div>
          <dt>Reward retention</dt>
          <dd>{((row.retentionBps ?? 0) / 100).toFixed(2)}%</dd>
        </div>
        <div>
          <dt>Extra purchase target</dt>
          <dd>{((row.supportBps ?? 0) / 100).toFixed(2)}%</dd>
        </div>
        <div>
          <dt>Distinct apps</dt>
          <dd>{row.apps}</dd>
        </div>
        <div>
          <dt>On-chain interactions</dt>
          <dd>{row.interactions}</dd>
        </div>
      </dl>
      <p className="small muted">
        Claim delays are capped at 30 days per allocation. Reward retention and
        extra purchases use the snapshot’s token policies.
      </p>
      {row.tokens?.map((token) => (
        <details className="token-detail" key={token.token}>
          <summary>{token.symbol} holdings & transfers</summary>
          <a
            className="address"
            href={`${EXPLORER}/token/${token.token}`}
            target="_blank"
            rel="noreferrer"
          >
            {token.token}
          </a>
          <dl className="token-values">
            {(
              [
                ["Claimed rewards", "claimed"],
                ["Rewards still held", "rewardHeld"],
                ["Rewards sold", "rewardSold"],
                ["Rewards otherwise sent", "rewardOtherOut"],
                ["Extra purchases", "bought"],
                ["Total sold", "sold"],
                ["Other outgoing", "otherOut"],
                ["Wallet balance", "balance"],
              ] as const
            ).map(([label, key]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{units(token[key], token)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ))}
    </details>
  );
}
export function Results({ payment }: { payment: PaymentRecord }) {
  const { report } = payment;
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const filtered = report.rows.filter((row) =>
    row.wallet.toLowerCase().includes(filter.trim().toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 25));
  const visible = filtered.slice(page * 25, page * 25 + 25);
  const csv = [
    "wallet,found,rank,score,tier,active_seats,launches,claimed_claims,eligible_claims,claim_delay_seconds,distinct_apps,interactions",
    ...report.rows.map((r) =>
      [
        r.wallet,
        r.found,
        r.rank,
        r.score,
        r.found ? TIERS[r.tier] : "Not ranked",
        r.seats,
        r.launches ?? "",
        r.claimedClaims ?? "",
        r.eligibleClaims ?? "",
        r.totalClaimDelay ?? "",
        r.apps ?? "",
        r.interactions ?? "",
      ].join(","),
    ),
  ].join("\n");
  return (
    <section className="results" aria-labelledby="results-title">
      <div className="section-heading">
        <div>
          <h2 id="results-title">{queryLabel(report.query)} results</h2>
          <p className="small muted">
            Snapshot #{report.snapshot.epoch} ·{" "}
            {new Date(report.snapshot.timestamp * 1000).toLocaleString()} ·{" "}
            {report.rows.length} returned
          </p>
        </div>
        <div className="button-row">
          <button
            className="button secondary"
            onClick={() =>
              download(
                `imd-epoch-${report.snapshot.epoch}.json`,
                JSON.stringify(payment, null, 2),
                "application/json",
              )
            }
          >
            Download JSON
          </button>
          <button
            className="button secondary"
            onClick={() =>
              download(
                `imd-epoch-${report.snapshot.epoch}.csv`,
                csv,
                "text/csv",
              )
            }
          >
            Download CSV
          </button>
        </div>
      </div>
      <p className="small">
        Payment confirmed.{" "}
        <a
          href={`${EXPLORER}/tx/${payment.hash}`}
          target="_blank"
          rel="noreferrer"
        >
          View Ethereum receipt ↗
        </a>
      </p>
      <label className="filter-label" htmlFor="filter">
        Filter these results by address
      </label>
      <input
        id="filter"
        type="search"
        value={filter}
        onChange={(e) => {
          setFilter(e.target.value);
          setPage(0);
        }}
        placeholder="Paste all or part of an address"
      />
      <div className="ranking-head" aria-hidden="true">
        <span>Rank</span>
        <span>Wallet / activity</span>
        <span>Score</span>
      </div>
      <ol className="ranking-list" aria-label="Wallet rankings">
        {visible.map((row) => (
          <li key={row.wallet} className="ranking-row">
            <span className="rank">{row.found ? `#${row.rank}` : "N/A"}</span>
            <div className="wallet-cell">
              <a
                className="address"
                href={`${EXPLORER}/address/${row.wallet}`}
                target="_blank"
                rel="noreferrer"
              >
                {row.wallet}
              </a>
              <p className="small muted">
                {row.found
                  ? `${TIERS[row.tier]} · ${row.seats} active seat${row.seats === 1 ? "" : "s"}`
                  : "Not in this snapshot"}
              </p>
            </div>
            <div className="score-number">
              {row.found ? (row.score / 100).toFixed(2) : "N/A"}
              <span className="small muted">{row.found ? "/ 100" : ""}</span>
            </div>
            {row.found && row.launches !== undefined && (
              <WalletDetail row={row} />
            )}
          </li>
        ))}
      </ol>
      {!visible.length && (
        <p role="status">
          No matching address in these results.{" "}
          <button
            className="text-button"
            onClick={() => {
              setFilter("");
              setPage(0);
            }}
          >
            Clear filter
          </button>
        </p>
      )}
      {pages > 1 && (
        <div className="pagination">
          <button
            className="button secondary"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </button>
          <span aria-live="polite">
            Page {page + 1} of {pages}
          </span>
          <button
            className="button secondary"
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
      <details className="provenance">
        <summary>Snapshot evidence & methodology</summary>
        <dl className="token-values">
          <div>
            <dt>Observation block</dt>
            <dd>
              <a
                href={`${EXPLORER}/block/${report.snapshot.block}`}
                target="_blank"
                rel="noreferrer"
              >
                {report.snapshot.block}
              </a>
            </dd>
          </div>
          <div>
            <dt>Reporter</dt>
            <dd className="address">{report.snapshot.reporter}</dd>
          </div>
          <div>
            <dt>Evidence hash</dt>
            <dd className="address">{report.snapshot.evidenceHash}</dd>
          </div>
          <div>
            <dt>Methodology hash</dt>
            <dd className="address">{report.snapshot.methodologyHash}</dd>
          </div>
        </dl>
        <p className="small muted">
          This saved snapshot is historical. Downloaded results do not refresh
          automatically. The appointed reporter attests the history; the
          contract checks accounting and ranks.
        </p>
      </details>
    </section>
  );
}
