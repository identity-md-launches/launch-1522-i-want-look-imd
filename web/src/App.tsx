import { RadarPanel } from "./RadarPanel";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Address } from "viem";
import { BOARD, BURN, EXPLORER, IMD } from "./config";
import {
  confirmPayment,
  connect,
  loadBoard,
  prepareQuery,
  sendPayment,
  switchNetwork,
} from "./chain";
import {
  decodeRecovery,
  errorMessage,
  PACKS,
  parseWallets,
  queryLabel,
  queryPrice,
  type BoardStatus,
  type PackSize,
  type PaymentRecord,
  type Report,
} from "./domain";
import { useWallet, type WalletOption } from "./wallet";
import { Results } from "./Results";

const PAYMENT_KEY = "imd-chadboard-pending-v1";
function readPending(): PaymentRecord | null {
  try {
    const saved = localStorage.getItem(PAYMENT_KEY);
    return saved ? decodeRecovery(saved) : null;
  } catch {
    return null;
  }
}
function Mark({ large = false }: { large?: boolean }) {
  return (
    <svg
      className={large ? "mark large-mark" : "mark"}
      aria-hidden="true"
      viewBox="0 0 48 48"
    >
      <rect width="48" height="48" rx="12" fill="currentColor" />
      <path
        d="M11 33V23h6v10zm10 0V16h6v17zm10 0V9h6v24z"
        className="mark-bars"
      />
    </svg>
  );
}
function Icon({ name }: { name: "arrow" | "search" | "wallet" | "refresh" }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {name === "arrow" ? (
        <path d="M5 12h14m-6-6 6 6-6 6" />
      ) : name === "search" ? (
        <>
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 4 4" />
        </>
      ) : name === "wallet" ? (
        <>
          <path d="M4 6h15v14H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12" />
          <path d="M15 11h6v5h-6z" />
        </>
      ) : (
        <>
          <path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7" />
        </>
      )}
    </svg>
  );
}
function Dialog({
  title,
  onClose,
  locked = false,
  children,
}: {
  title: string;
  onClose: () => void;
  locked?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!locked) onClose();
      }}
      aria-labelledby="dialog-title"
    >
      <div className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <button
          className="close-button"
          onClick={onClose}
          disabled={locked}
          aria-label="Close dialog"
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
function SnapshotStatus({
  status,
  refresh,
}: {
  status: BoardStatus;
  refresh: () => void;
}) {
  return (
    <section className="snapshot-strip" aria-label="Board status">
      <div className="snapshot-state">
        <span
          className={`status-dot ${status.kind === "ready" && !status.snapshot.stale ? "ready" : ""}`}
        />
        <span>
          {status.kind === "loading"
            ? "Checking the Ethereum board…"
            : status.kind === "empty"
              ? "Awaiting the first snapshot"
              : status.kind === "error"
                ? "Could not reach Ethereum"
                : status.snapshot.stale
                  ? "Snapshot is out of date"
                  : status.snapshot.source === "service"
                    ? `Snapshot ${status.snapshot.snapshotId} available (data service)`
                    : `Snapshot #${status.snapshot.epoch} available`}
        </span>
      </div>
      <button
        className="text-button"
        onClick={refresh}
        disabled={status.kind === "loading"}
      >
        <Icon name="refresh" />
        Refresh
      </button>
    </section>
  );
}

export default function App() {
  const wallet = useWallet();
  const [status, setStatus] = useState<BoardStatus>({ kind: "loading" });
  const [mode, setMode] = useState<"wallets" | "leaders">("wallets");
  const [input, setInput] = useState("");
  const [size, setSize] = useState<PackSize>(10);
  const [fieldError, setFieldError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<Report | null>(null);
  const [walletOpen, setWalletOpen] = useState(false);
  const [walletError, setWalletError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [consent, setConsent] = useState(false);
  const [paymentError, setPaymentError] = useState("");
  const [paying, setPaying] = useState(false);
  const [pending, setPending] = useState<PaymentRecord | null>(readPending);
  const [confirmed, setConfirmed] = useState<PaymentRecord | null>(null);
  const [checking, setChecking] = useState(false);
  const [paymentNotice, setPaymentNotice] = useState("");
  const [storageWarning, setStorageWarning] = useState("");
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const textRef = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef(false);
  const refreshId = useRef(0);
  const refresh = useCallback(async () => {
    const id = ++refreshId.current;
    setStatus({ kind: "loading" });
    try {
      const result = await loadBoard();
      if (id === refreshId.current) setStatus(result);
    } catch (error) {
      if (id === refreshId.current)
        setStatus({ kind: "error", message: errorMessage(error) });
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  let count = 0;
  try {
    count = parseWallets(input).length;
  } catch {
    /* Validate explicitly on submit. */
  }
  const missingValue =
    status.kind === "loading"
      ? "Checking…"
      : status.kind === "error"
        ? "Unavailable"
        : "Not published";
  const serviceSnapshot = status.kind === "ready" && status.snapshot.source === "service";
  const price =
    mode === "leaders"
      ? queryPrice({ kind: "leaders", count: size })
      : count
        ? (count / 10).toFixed(1)
        : "0.1";

  const openWallet = () => {
    setWalletError("");
    setWalletOpen(true);
  };
  async function chooseWallet(option: WalletOption) {
    if (connecting) return;
    setConnecting(true);
    setWalletError("");
    try {
      const account = await connect(option.provider);
      wallet.setSelected(option);
      wallet.setAccount(account);
      setWalletOpen(false);
    } catch (error) {
      setWalletError(errorMessage(error));
    } finally {
      setConnecting(false);
    }
  }
  async function changeNetwork() {
    if (!wallet.selected) return;
    setConnecting(true);
    setPaymentError("");
    try {
      await switchNetwork(wallet.selected.provider);
      wallet.setChainId(
        Number(
          await wallet.selected.provider.request({ method: "eth_chainId" }),
        ),
      );
    } catch (error) {
      setPaymentError(errorMessage(error));
    } finally {
      setConnecting(false);
    }
  }
  async function checkQuery(event: React.FormEvent) {
    event.preventDefault();
    if (busy || pending) return;
    setFieldError("");
    setNotice("");
    let query;
    try {
      query =
        mode === "wallets"
          ? { kind: "wallets" as const, wallets: parseWallets(input) }
          : { kind: "leaders" as const, count: size };
    } catch (error) {
      setFieldError(errorMessage(error));
      textRef.current?.focus();
      return;
    }
    setBusy(true);
    setNotice("Checking snapshot availability…");
    try {
      const result = await prepareQuery(query, setNotice);
      setReview(result);
      setConsent(false);
      setPaymentError("");
      setNotice("Query checked. Review the amount before paying.");
      setStatus({ kind: "ready", snapshot: result.snapshot });
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function checkPayment(record: PaymentRecord) {
    if (inFlight.current) return;
    inFlight.current = true;
    setChecking(true);
    setPaymentNotice(
      "Waiting for two Ethereum confirmations. Keep this page open, or return to check the same payment.",
    );
    try {
      await confirmPayment(record);
      setConfirmed(record);
      setPending(null);
      setPaymentNotice("Payment confirmed. Your query results are ready.");
      try {
        localStorage.removeItem(PAYMENT_KEY);
      } catch {
        /* The receipt remains visible. */
      }
    } catch (error) {
      setPaymentNotice(
        `${errorMessage(error)} Your payment reference is kept below. Check it again; do not send another payment while it is unresolved.`,
      );
    } finally {
      inFlight.current = false;
      setChecking(false);
    }
  }
  async function pay() {
    if (
      !review ||
      !wallet.selected ||
      !wallet.account ||
      !consent ||
      paying ||
      pending
    )
      return;
    setPaying(true);
    setPaymentError("");
    try {
      const hash = await sendPayment(
        wallet.selected.provider,
        wallet.account,
        review,
      );
      const record = {
        hash,
        account: wallet.account as Address,
        report: review,
        amount: queryPrice(review.query),
      };
      setPending(record);
      setReview(null);
      setConfirmed(null);
      try {
        localStorage.setItem(PAYMENT_KEY, JSON.stringify(record));
      } catch {
        setStorageWarning(
          "This browser could not save payment recovery. Download the recovery file below before closing the page.",
        );
      }
      void checkPayment(record);
    } catch (error) {
      setPaymentError(errorMessage(error));
    } finally {
      setPaying(false);
    }
  }
  async function restoreRecovery(file: File | undefined) {
    if (!file || pending || paying || busy) return;
    try {
      if (file.size > 2_000_000)
        throw new Error(
          "Choose a ChadBoard recovery JSON file smaller than 2 MB.",
        );
      const record = decodeRecovery(await file.text());
      setPending(record);
      setConfirmed(null);
      setPaymentNotice(
        "Saved payment loaded. Check its Ethereum receipt to recover these results.",
      );
      try {
        localStorage.setItem(PAYMENT_KEY, JSON.stringify(record));
      } catch {
        setStorageWarning(
          "Local storage is unavailable. Keep your recovery file until the payment is confirmed.",
        );
      }
      setRecoveryNotice(
        "Payment loaded. Use “Check payment status” above; no new payment will be sent.",
      );
    } catch (error) {
      setRecoveryNotice(errorMessage(error));
    }
  }
  function saveRecovery() {
    if (!pending) return;
    const blob = new Blob([JSON.stringify(pending, null, 2)], {
      type: "application/json",
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `imd-payment-${pending.hash}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  return (
    <>
      <a className="skip-link" href="#query">
        Skip to query
      </a>
      <header className="site-header wrap">
        <a className="brand" href="#">
          <Mark />
          <span>
            IMD <strong>ChadBoard</strong>
          </span>
        </a>
        <div className="header-actions">
          <a className="header-link" href="#method">
            How it works
          </a>
          <button className="button wallet-button" onClick={openWallet}>
            <Icon name="wallet" />
            {wallet.account ? "Wallet connected" : "Connect wallet"}
          </button>
        </div>
      </header>
      <main className="wrap">
        <div className="page-heading">
          <div>
            <h1>Wallets, ranked by action.</h1>
            <p>Explore the on-chain activity of activated IMD seats.</p>
          </div>
          <span className="network-label">
            <span className="network-glyph" aria-hidden="true">
              ◇
            </span>{" "}
            Ethereum mainnet
          </span>
        </div>
        <div className="workspace">
          <section
            className="query-panel"
            id="query"
            aria-labelledby="query-heading"
          >
            <div className="panel-heading">
              <h2 id="query-heading">Run a query</h2>
              <Icon name="search" />
            </div>
            <div className="mode-switch" role="group" aria-label="Query type">
              <button
                aria-pressed={mode === "wallets"}
                onClick={() => {
                  setMode("wallets");
                  setFieldError("");
                  setNotice("");
                }}
                disabled={busy}
              >
                Wallets
              </button>
              <button
                aria-pressed={mode === "leaders"}
                onClick={() => {
                  setMode("leaders");
                  setFieldError("");
                  setNotice("");
                }}
                disabled={busy}
              >
                Leaderboard
              </button>
            </div>
            <form onSubmit={checkQuery} noValidate>
              {mode === "wallets" ? (
                <div className="wallet-input">
                  <div className="label-row">
                    <label htmlFor="wallets">Ethereum wallet addresses</label>
                    {wallet.account && (
                      <button
                        type="button"
                        className="text-button"
                        disabled={busy}
                        onClick={() => {
                          setInput(wallet.account ?? "");
                          setFieldError("");
                        }}
                      >
                        Use mine
                      </button>
                    )}
                  </div>
                  <textarea
                    ref={textRef}
                    id="wallets"
                    name="wallets"
                    value={input}
                    onChange={(e) => {
                      setInput(e.target.value);
                      setFieldError("");
                      setNotice("");
                    }}
                    placeholder="Paste one or more 0x addresses"
                    spellCheck={false}
                    autoCapitalize="none"
                    autoComplete="off"
                    rows={3}
                    aria-invalid={!!fieldError}
                    aria-describedby={
                      fieldError ? "wallet-error wallet-hint" : "wallet-hint"
                    }
                    disabled={busy}
                  />
                  <p id="wallet-hint" className="small muted">
                    Separate with commas or new lines. Up to 100 unique wallets.
                  </p>
                  <p
                    id="wallet-error"
                    className="error field-error"
                    role={fieldError ? "alert" : undefined}
                  >
                    {fieldError}
                  </p>
                </div>
              ) : (
                <fieldset className="pack-fieldset">
                  <legend>Choose a leaderboard size</legend>
                  <div className="pack-grid">
                    {PACKS.map((pack) => (
                      <label
                        className={`pack-option ${size === pack.count ? "selected" : ""}`}
                        key={pack.count}
                      >
                        <input
                          type="radio"
                          name="pack"
                          value={pack.count}
                          checked={size === pack.count}
                          disabled={busy}
                          onChange={() => {
                            setSize(pack.count);
                            setNotice("");
                          }}
                        />
                        <span>
                          <strong>Top {pack.count.toLocaleString()}</strong>
                          <span className="small muted">{pack.price} IMD</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
              <div className="query-total">
                <div>
                  <span className="small muted">Query fee</span>
                  <div className="price">
                    {price} <span>IMD</span>
                  </div>
                </div>
                <span className="small muted">
                  {mode === "wallets"
                    ? count
                      ? `${count} unique wallet${count === 1 ? "" : "s"}`
                      : "Per wallet"
                    : "Fixed price"}
                  <br />+ Ethereum gas
                </span>
              </div>
              <button
                type="submit"
                className="button primary query-submit"
                disabled={busy || !!pending}
              >
                {busy
                  ? "Checking query…"
                  : pending
                    ? "Resolve pending payment below"
                    : "Check query"}
                <Icon name="arrow" />
              </button>
              <p className="small payment-caption">
                Review first. Your fee goes to the dead address.
              </p>
            </form>
            <div className="query-notice" role="status" aria-live="polite">
              {notice}
            </div>
          </section>
          <aside className="score-guide" aria-labelledby="score-heading">
            <div className="guide-title">
              <span className="guide-symbol" aria-hidden="true">
                ↗
              </span>
              <span className="small">Participation leaves a record.</span>
            </div>
            <h2 id="score-heading">
              What makes
              <br />a Chad?
            </h2>
            <p>
              {serviceSnapshot ? "An Ethereum holding score out of 100." : "Five signals. One score out of 100."}
              <br />
              {serviceSnapshot ? "Not yet published on the ChadBoard contract." : "Measured from published on-chain snapshots."}
            </p>
            <ol className="score-factors">
              {(serviceSnapshot ? [
                ["IMD retention", "30", "100%"],
                ["Current holding period", "20", "66.667%"],
                ["Longest holding period", "10", "33.333%"],
                ["No outgoing transfers", "15", "50%"],
                ["IMD balance", "15", "50%"],
                ["Activated seats", "10", "33.333%"],
              ] : [
                ["Launches initiated", "30", "100%"],
                ["Rewards held", "30", "100%"],
                ["Claim timing", "15", "50%"],
                ["Extra token purchases", "15", "50%"],
                ["Ecosystem app activity", "10", "33.333%"],
              ]).map(([label, points, width], index) => (
                <li key={label}>
                  <span className="factor-index">0{index + 1}</span>
                  <div>
                    <div className="factor-label">
                      <span>{label}</span>
                      <span>{points} pts</span>
                    </div>
                    <div className="factor-track" aria-hidden="true">
                      <span style={{ width }} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <a className="guide-link" href="#method">
              Read the scoring method <Icon name="arrow" />
            </a>
          </aside>
        </div>
        <SnapshotStatus status={status} refresh={() => void refresh()} />
        <section className="board-overview" aria-label="Snapshot overview">
          <div>
            <span className="small muted">Total seats</span>
            <strong>
              {status.kind === "ready"
                ? status.snapshot.seatCensusAvailable === false ? "Unavailable" : BigInt(status.snapshot.totalSeats).toLocaleString()
                : missingValue}
            </strong>
          </div>
          <div>
            <span className="small muted">Activated seats</span>
            <strong>
              {status.kind === "ready"
                ? status.snapshot.seatCensusAvailable === false ? "Unavailable" : BigInt(status.snapshot.activatedSeats).toLocaleString()
                : missingValue}
            </strong>
          </div>
          <div>
            <span className="small muted">Ranked wallets</span>
            <strong>
              {status.kind === "ready"
                ? status.snapshot.wallets.toLocaleString()
                : missingValue}
            </strong>
          </div>
          <div>
            <span className="small muted">Observed at</span>
            <strong className="observed-date">
              {status.kind === "ready"
                ? new Date(status.snapshot.timestamp * 1000).toLocaleString()
                : missingValue}
            </strong>
          </div>
        </section>
        {status.kind !== "loading" && (
          <div className="availability-note">
            {status.kind === "empty" ? (
              <p>
                The board is deployed. Its operator has not published a snapshot
                yet. Queries and payments will become available when a current
                snapshot is published.
              </p>
            ) : status.kind === "error" ? (
              <div>
                <p>
                  Live data is unavailable. Payments are paused. Refresh to
                  retry.
                </p>
                <details>
                  <summary>Connection details</summary>
                  <p className="small">{status.message}</p>
                </details>
              </div>
            ) : status.snapshot.stale ? (
              <p>
                This snapshot is out of date or uses an older configuration.
                Payments are paused until the operator publishes a current
                snapshot.
              </p>
            ) : (
              <p>
                Data observed at Ethereum block{" "}
                <a
                  href={`${EXPLORER}/block/${status.snapshot.block}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {status.snapshot.block}
                </a>
                . Results describe this snapshot, not real-time wallet activity.
                {status.snapshot.source === "service" &&
                  " This is the data service’s Ethereum holding score, not the published ChadBoard score. Radar observations cannot change its ranking."}
              </p>
            )}
          </div>
        )}
        <RadarPanel />
        {pending && (
          <section className="payment-status" aria-labelledby="payment-title">
            <h2 id="payment-title">Your payment is being tracked</h2>
            <p>
              {pending.amount} IMD · {queryLabel(pending.report.query)}
            </p>
            <p role="status">
              {paymentNotice ||
                "A previous payment was found in this browser. Check its status to retrieve your prepared results."}
            </p>
            <a
              className="address"
              href={`${EXPLORER}/tx/${pending.hash}`}
              target="_blank"
              rel="noreferrer"
            >
              {pending.hash}
            </a>
            {storageWarning && (
              <p className="error" role="alert">
                {storageWarning}
              </p>
            )}
            <div className="button-row">
              <button
                className="button primary"
                onClick={() => void checkPayment(pending)}
                disabled={checking}
              >
                {checking ? "Checking confirmations…" : "Check payment status"}
              </button>
              <button className="button secondary" onClick={saveRecovery}>
                Save recovery file
              </button>
            </div>
            <details>
              <summary>Payment replaced, cancelled or reverted?</summary>
              <p className="small">
                Check the receipt in your wallet or on Etherscan first. If you
                sped up a payment, enter the replacement hash; the amount,
                sender and recipient are verified again.
              </p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = new FormData(event.currentTarget);
                  const hash = String(data.get("hash") ?? "").trim();
                  if (!/^0x[0-9a-fA-F]{64}$/.test(hash)) {
                    setPaymentNotice(
                      "Enter the full 66-character transaction hash.",
                    );
                    return;
                  }
                  const record = { ...pending, hash: hash as `0x${string}` };
                  setPending(record);
                  try {
                    localStorage.setItem(PAYMENT_KEY, JSON.stringify(record));
                  } catch {
                    /* Recovery download remains available. */
                  }
                  void checkPayment(record);
                }}
              >
                <label htmlFor="replacement">
                  Replacement transaction hash
                </label>
                <input
                  id="replacement"
                  name="hash"
                  placeholder="0x…"
                  disabled={checking}
                />
                <button className="button secondary" disabled={checking}>
                  Check replacement
                </button>
              </form>
              <p className="small">
                If the transfer was cancelled or reverted, discard this local
                record to start again. A confirmed transfer is irreversible;
                discarding its record does not refund it.
              </p>
              <button
                className="text-button"
                disabled={checking}
                onClick={() => {
                  if (
                    window.confirm(
                      "Discard this payment record? Save its recovery file first. This does not refund any IMD already sent.",
                    )
                  ) {
                    setPending(null);
                    setPaymentNotice("");
                    try {
                      localStorage.removeItem(PAYMENT_KEY);
                    } catch {
                      /* Local-only state. */
                    }
                  }
                }}
              >
                Discard local payment record
              </button>
            </details>
          </section>
        )}
        {confirmed && <Results key={confirmed.hash} payment={confirmed} />}
        <section
          className="method-section"
          id="method"
          aria-labelledby="method-heading"
        >
          <div className="method-intro">
            <h2 id="method-heading">The record behind the rank.</h2>
            <p>
              A view of ecosystem participation, built from the wallets
              associated with activated IMD NFT seats.
            </p>
            <a
              className="inline-link"
              href={`${EXPLORER}/address/${BOARD}`}
              target="_blank"
              rel="noreferrer"
            >
              View ChadBoard on Etherscan ↗
            </a>
          </div>
          <div className="explainers">
            <details open>
              <summary>What does the score measure?</summary>
              {serviceSnapshot ? <p>The data service measures IMD retention (30 points), current holding duration (20), longest holding duration (10), no outgoing transfers (15), balance (15), and verified seat activation (10). It uses Ethereum state and Transfer history. This is separate from the contract’s published participation score.</p> : <p>
                Launches earn up to 30 points, reward retention 30, claim timing
                15, extra token purchases 15, and distinct ecosystem apps 10.
                The contract stores scores from 0 to 10,000; this interface
                displays them out of 100.
              </p>}
              <p>
                Observer: below 25. Contributor: 25–49.99. Chad: 50–74.99.
                GigaChad: 75–100. These tiers describe measured participation.
              </p>
            </details>
            <details>
              <summary>Where does the data come from?</summary>
              <p>
                The appointed reporter collects historical Ethereum events and
                publishes immutable snapshots. ChadBoard checks the accounting
                and ordering, but does not independently prove the reporter
                included every event.
              </p>
              <p>
                Only recognized on-chain app interactions count. Browsing a
                website or connecting a wallet is not observable. Rewards sent
                elsewhere are not automatically classified as sold.
              </p>
            </details>
            <details>
              <summary>How do query payments work?</summary>
              <p>
                Wallet queries cost 0.1 IMD per unique address. Leaderboards
                cost 0.1, 0.5, 1 or 2 IMD for Top 10, 50, 100 or 1,000. A pack
                returns up to that many available wallets. The returned count is
                shown before payment.
              </p>
              <p>
                The site checks that results exist before asking you to send
                IMD. Your wallet sends the exact amount directly to the dead
                address, plus Ethereum gas. No token approval is requested.
                Transfers are irreversible and do not reduce the token’s
                reported total supply.
              </p>
              <p>
                The fee is an interface policy. The contract’s read functions
                are public and have no on-chain paywall. There is no backend
                account or private dataset.
              </p>
              <dl className="address-list">
                <div>
                  <dt>Dead address</dt>
                  <dd>
                    <a
                      className="address"
                      href={`${EXPLORER}/address/${BURN}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {BURN}
                    </a>
                  </dd>
                </div>
                <div>
                  <dt>IMD token · Ethereum</dt>
                  <dd>
                    <a
                      className="address"
                      href={`${EXPLORER}/token/${IMD}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {IMD}
                    </a>
                  </dd>
                </div>
              </dl>
            </details>
            <details>
              <summary>Why might a wallet be missing?</summary>
              <p>
                {serviceSnapshot ? "The service uses verified seat holders or activated seats when configured, otherwise indexed IMD holders. Radar-only wallets are not ranked." : "A wallet must be associated with an activated seat in the selected snapshot."} Later activity appears only after another
                snapshot is published. If none of your wallets is found, the
                interface will not request payment.
              </p>
              <p>
                Duplicate addresses are counted once. A mixed query still costs
                0.1 IMD per unique requested wallet, including absent wallets;
                the matched count is shown before payment.
              </p>
            </details>
            <details>
              <summary>Where are my results saved?</summary>
              <p>
                Results stay in this tab. Download JSON for the full snapshot,
                token observations and payment receipt, or CSV for the wallet
                summary. Pending payments and prepared results are saved in this
                browser so you can check them after a reload.
              </p>
              <p>
                No analytics or account server is used. Public Ethereum RPC
                providers receive your queried addresses. Your wallet handles
                signing; this site never asks for a seed phrase or private key.
              </p>
              <label className="recovery-label" htmlFor="recovery">
                Restore a saved payment
              </label>
              <input
                id="recovery"
                type="file"
                accept=".json,application/json"
                disabled={!!pending || paying || busy}
                onChange={(event) => {
                  void restoreRecovery(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
              <p className="small muted">
                Choose your own saved recovery JSON. Its receipt is verified on
                Ethereum; the prepared report comes from your file.
              </p>
              <p role="status" className="small">
                {recoveryNotice}
              </p>
            </details>
          </div>
        </section>
      </main>
      <footer className="wrap site-footer">
        <span>IMD ChadBoard</span>
        <span>Built on participation. Recorded on Ethereum.</span>
        <a href="#query">Back to query ↑</a>
      </footer>
      {walletOpen && (
        <Dialog
          title={wallet.account ? "Connected wallet" : "Connect a wallet"}
          onClose={() => setWalletOpen(false)}
          locked={connecting}
        >
          {wallet.account ? (
            <>
              <p className="small muted">
                {wallet.selected?.name} ·{" "}
                {wallet.chainId === 1
                  ? "Ethereum mainnet"
                  : "Different network"}
              </p>
              <p className="address connected-address">{wallet.account}</p>
              <button
                className="button secondary"
                onClick={() => {
                  wallet.disconnect();
                  setWalletOpen(false);
                }}
              >
                Disconnect from this site
              </button>
            </>
          ) : (
            <>
              <p>
                Use an Ethereum wallet installed in this browser, or open this
                site in your wallet’s browser.
              </p>
              {wallet.options.length ? (
                <div className="wallet-options">
                  {wallet.options.map((option) => (
                    <button
                      className="button secondary"
                      disabled={connecting}
                      key={option.id}
                      onClick={() => void chooseWallet(option)}
                    >
                      <Icon name="wallet" />
                      {connecting ? "Check your wallet…" : option.name}
                      <Icon name="arrow" />
                    </button>
                  ))}
                </div>
              ) : (
                <p className="callout">
                  No browser wallet detected. Open the site in your wallet’s
                  browser, or install a wallet extension, then reload this page.
                </p>
              )}
              <p className="small muted">
                Connecting shares your public address. It does not send a
                transaction.
              </p>
            </>
          )}
          {walletError && (
            <p className="error" role="alert">
              {walletError}
            </p>
          )}
        </Dialog>
      )}
      {review && !walletOpen && (
        <Dialog
          title="Review your query"
          onClose={() => {
            if (!paying) setReview(null);
          }}
          locked={paying}
        >
          <dl className="review-details">
            <div>
              <dt>Query</dt>
              <dd>{queryLabel(review.query)}</dd>
            </div>
            <div>
              <dt>Available results</dt>
              <dd>
                {review.rows.filter((r) => r.found).length} ranked /{" "}
                {review.query.kind === "wallets"
                  ? review.query.wallets.length
                  : review.query.count}{" "}
                requested
              </dd>
            </div>
            <div>
              <dt>Snapshot</dt>
              <dd>
                #{review.snapshot.epoch} · Block {review.snapshot.block}
              </dd>
            </div>
            <div>
              <dt>Amount to send</dt>
              <dd>
                <strong>{queryPrice(review.query)} IMD</strong> + Ethereum gas
              </dd>
            </div>
          </dl>
          <div className="recipient">
            <span className="small muted">Recipient · dead address</span>
            <a
              className="address"
              href={`${EXPLORER}/address/${BURN}`}
              target="_blank"
              rel="noreferrer"
            >
              {BURN}
            </a>
          </div>
          <p className="small">
            This sends IMD directly to the dead address. It is irreversible.
            Results are a historical snapshot; the underlying contract data is
            public.
          </p>
          <label className="consent">
            <input
              type="checkbox"
              checked={consent}
              disabled={paying}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <span>I understand the fee and irreversible transfer.</span>
          </label>
          {!wallet.account ? (
            <button className="button primary full-width" onClick={openWallet}>
              Connect wallet to continue
            </button>
          ) : wallet.chainId !== 1 ? (
            <button
              className="button primary full-width"
              disabled={connecting}
              onClick={() => void changeNetwork()}
            >
              {connecting ? "Switching network…" : "Switch to Ethereum"}
            </button>
          ) : (
            <>
              <p className="small muted">
                Paying from <span className="address">{wallet.account}</span>
              </p>
              <button
                className="button primary full-width"
                disabled={!consent || paying}
                onClick={() => void pay()}
              >
                {paying
                  ? "Confirm transfer in your wallet…"
                  : `Send ${queryPrice(review.query)} IMD & view results`}
              </button>
            </>
          )}
          {paymentError && (
            <p className="error" role="alert">
              {paymentError}
            </p>
          )}
        </Dialog>
      )}
    </>
  );
}
