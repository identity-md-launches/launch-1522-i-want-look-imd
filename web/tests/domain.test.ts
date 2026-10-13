import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  encodeAbiParameters,
  encodeEventTopics,
  erc20Abi,
  getAddress,
  keccak256,
  stringToHex,
  type Address,
  type TransactionReceipt,
} from "viem";
import { readFileSync } from "node:fs";
import { boardAbi } from "../src/board-abi";
import { ABI_HASH, BOARD, BURN, IMD } from "../src/config";
import {
  decodeRecovery,
  PACKS,
  parseWallets,
  queryAmount,
  queryPrice,
  formatDelay,
  type PaymentRecord,
} from "../src/domain";
import { verifyReceipt } from "../src/chain";

const account = "0x1111111111111111111111111111111111111111" as Address;
const hash = `0x${"ab".repeat(32)}` as const;
const record = {
  hash,
  account,
  amount: "0.1",
  report: { query: { kind: "wallets", wallets: [account] } },
} as PaymentRecord;
function receipt(
  from = account,
  to = BURN,
  value = 10n ** 17n,
  status = "success",
  token = IMD,
): TransactionReceipt {
  return {
    status,
    transactionHash: hash,
    from: account,
    to: IMD,
    logs: [
      {
        address: token,
        topics: encodeEventTopics({
          abi: erc20Abi,
          eventName: "Transfer",
          args: { from, to },
        }),
        data: encodeAbiParameters([{ type: "uint256" }], [value]),
      },
    ],
  } as TransactionReceipt;
}
test("Ethereum input trims, splits, checks addresses and deduplicates before pricing", () => {
  assert.deepEqual(
    parseWallets(`  ${BOARD},\n${getAddress(BOARD)}; ${BURN}`),
    parseWallets(`${BOARD} ${BURN}`),
  );
  assert.equal(
    queryPrice({ kind: "wallets", wallets: parseWallets(`${BOARD},${BOARD}`) }),
    "0.1",
  );
  assert.throws(() => parseWallets(""), /Enter at least one/);
  assert.throws(() => parseWallets("alice.eth"), /full 42-character/);
  assert.throws(() => parseWallets("0x1234"), /Check this address/);
  assert.throws(
    () => parseWallets("0x000000000000000000000000000000000000dEAd"),
    /valid checksum/,
  );
  const addresses = Array.from(
    { length: 101 },
    (_, i) => `0x${(i + 1).toString(16).padStart(40, "0")}`,
  );
  assert.equal(parseWallets(addresses.slice(0, 100).join("\n")).length, 100);
  assert.throws(() => parseWallets(addresses.join("\n")), /up to 100 unique/);
});
test("Exact bigint pricing and every fixed pack comply with the 2 IMD leaderboard cap", () => {
  for (const pack of PACKS) {
    const query = { kind: "leaders", count: pack.count } as const;
    assert.equal(queryPrice(query), pack.price);
    assert.ok(queryAmount(query) <= 2n * 10n ** 18n);
  }
  assert.equal(
    queryAmount({ kind: "wallets", wallets: Array(37).fill(account) }),
    37n * 10n ** 17n,
  );
});
test("Payment requires the exact IMD token, sender, dead recipient, amount and successful receipt", () => {
  assert.doesNotThrow(() => verifyReceipt(record, receipt()));
  assert.throws(() => verifyReceipt(record, receipt(BOARD)), /No matching IMD/);
  assert.throws(
    () => verifyReceipt(record, receipt(account, BOARD)),
    /No matching IMD/,
  );
  assert.throws(
    () => verifyReceipt(record, receipt(account, BURN, 1n)),
    /No matching IMD/,
  );
  assert.throws(
    () =>
      verifyReceipt(
        record,
        receipt(account, BURN, 10n ** 17n, "success", BOARD),
      ),
    /No matching IMD/,
  );
  assert.throws(
    () => verifyReceipt(record, receipt(account, BURN, 10n ** 17n, "reverted")),
    /reverted/,
  );
  assert.throws(
    () =>
      verifyReceipt(record, {
        ...receipt(),
        transactionHash: `0x${"cd".repeat(32)}`,
      }),
    /does not match/,
  );
  assert.throws(
    () => verifyReceipt(record, { ...receipt(), from: BOARD }),
    /paying wallet/,
  );
});
test("ABI canonical keccak matches the pinned deployment hash", () => {
  function canonical(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value !== null && typeof value === "object")
      return `{${Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`)
        .join(",")}}`;
    return JSON.stringify(value);
  }
  assert.equal(keccak256(stringToHex(canonical(boardAbi))), ABI_HASH);
});
test("Claim delay preserves zero and explicitly marks unclaimed allocations", () => {
  assert.equal(formatDelay("0", 1), "0 sec");
  assert.equal(formatDelay("0", 0), "No claims");
  assert.equal(formatDelay("7200", 2), "1.0 hr");
  assert.equal(formatDelay("2592000"), "30.0 days");
});
test("Static metadata and transfer recipient are present in the source", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  for (const name of ["description", "og:title", "og:image"])
    assert.ok(html.includes(`"${name}"`));
  assert.ok(html.includes("./favicon.svg"));
  assert.equal(BURN, "0x000000000000000000000000000000000000dEaD");
});

test("Recovery rejects malformed files, inconsistent fees and unsafe display fields", () => {
  const valid = {
    ...record,
    report: {
      query: record.report.query,
      createdAt: 1000,
      snapshot: {
        epoch: "1",
        block: "900",
        timestamp: 100,
        publishedAt: 101,
        totalSeats: "10",
        activatedSeats: "5",
        wallets: 1,
        stale: false,
        currentConfiguration: true,
        reporter: account,
        evidenceHash: hash,
        methodologyHash: hash,
      },
      rows: [
        {
          wallet: account,
          found: true,
          rank: 1,
          score: 7650,
          tier: 3,
          seats: 1,
        },
      ],
    },
  };
  assert.deepEqual(decodeRecovery(JSON.stringify(valid)), valid);
  assert.throws(() => decodeRecovery("no JSON"), /valid ChadBoard/);
  assert.throws(() => decodeRecovery("{}"), /valid ChadBoard/);
  assert.throws(
    () => decodeRecovery(JSON.stringify({ ...valid, amount: "2" })),
    /valid ChadBoard/,
  );
  const modified = structuredClone(valid);
  modified.report.rows[0].score = -1;
  assert.throws(
    () => decodeRecovery(JSON.stringify(modified)),
    /valid ChadBoard/,
  );
  const badQuery = structuredClone(valid);
  badQuery.report.query = { kind: "wallets", wallets: [] };
  assert.throws(
    () => decodeRecovery(JSON.stringify(badQuery)),
    /valid ChadBoard/,
  );
  const badDate = structuredClone(valid);
  badDate.report.snapshot.timestamp = Number.MAX_SAFE_INTEGER;
  assert.throws(
    () => decodeRecovery(JSON.stringify(badDate)),
    /valid ChadBoard/,
  );
});
