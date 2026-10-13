// Production-export interaction checks. All RPC responses and wallet signing are fixtures;
// this script never sends a transaction or queries a public service.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, extname, join } from "node:path";
import { pathToFileURL } from "node:url";
import {
  decodeFunctionData,
  encodeFunctionResult,
  encodeEventTopics,
  encodeAbiParameters,
  erc20Abi,
  type Address,
} from "viem";
import { boardAbi } from "../src/board-abi";
import { BOARD, IMD, BURN } from "../src/config";

const playwrightPath = process.env.IMD_PLAYWRIGHT;
if (!playwrightPath)
  throw new Error(
    "Set IMD_PLAYWRIGHT to an external Playwright index.mjs. See README.",
  );
const { chromium, webkit } = await import(pathToFileURL(playwrightPath).href);
const root = resolve(process.env.IMD_EXPORT ?? "../dist");
const output = resolve(
  process.env.IMD_BROWSER_OUTPUT ?? "../test/scratch/browser",
);
await mkdir(output, { recursive: true });
const runtime = (
  await readFile(
    new URL("../tests/fixtures/board-runtime.hex", import.meta.url),
    "utf8",
  )
).trim();
const server = createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url ?? "/", "http://localhost").pathname,
    );
    if (!name.startsWith("/preview/")) {
      res.writeHead(404);
      res.end();
      return;
    }
    const file = resolve(root, name.slice("/preview/".length) || "index.html");
    if (!file.startsWith(root + "/")) {
      res.writeHead(403);
      res.end();
      return;
    }
    const mime: Record<string, string> = {
      ".html": "text/html",
      ".js": "text/javascript",
      ".css": "text/css",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".json": "application/json",
    };
    res.writeHead(200, {
      "Content-Type": mime[extname(file)] ?? "application/octet-stream",
    });
    res.end(await readFile(file));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
const address = server.address();
if (!address || typeof address === "string") throw new Error("No preview port");
const url = `http://127.0.0.1:${address.port}/preview/`;
const account = "0x1111111111111111111111111111111111111111" as Address;
const txHash = `0x${"ab".repeat(32)}` as const;
const blockHash = `0x${"bc".repeat(32)}` as const;
let mode = "empty";
let paidAmount = 10n ** 17n;
let receiptAvailable = true;
let leaderCalls: number[] = [];
let errors: string[] = [];
const observations = {
  claimed: 1000n,
  bought: 500n,
  sold: 0n,
  otherOut: 0n,
  rewardHeld: 1000n,
  rewardSold: 0n,
  rewardOtherOut: 0n,
  balance: 1500n,
};
const reportStats = {
  metrics: {
    activeSeats: 1,
    launches: 12,
    eligibleClaims: 4,
    claimedClaims: 3,
    totalClaimDelay: 3600n,
    maxClaimDelay: 1800n,
    interactions: 10,
    distinctApps: 4,
  },
  rank: 1,
  score: 7650,
  retentionBps: 10000,
  supportBps: 2500,
};
const epochData = () => ({
  status: 2,
  snapshot: {
    blockNumber: 900n,
    timestamp: BigInt(Math.floor(Date.now() / 1000) - 60),
    blockHash,
    totalSeats: 1200n,
    activatedSeats: 1100n,
    walletCount: 1000,
    evidenceHash: blockHash,
    configuration: 1n,
  },
  configuration: 1n,
  maxAge: 172800n,
  publishedAt: BigInt(Math.floor(Date.now() / 1000)),
  seatsWritten: 1100n,
  walletsWritten: 1000,
  reporter: account,
  seatNFT: BOARD,
  methodologyHash: blockHash,
});
function rpcResult(request: any): unknown {
  switch (request.method) {
    case "eth_chainId":
      return "0x1";
    case "eth_blockNumber":
      return "0x3e8";
    case "eth_getCode":
      return request.params[0].toLowerCase() === BOARD.toLowerCase()
        ? mode === "code-mismatch"
          ? "0x6000"
          : runtime
        : "0x6000";
    case "eth_getTransactionByHash":
      return null;
    case "eth_getTransactionReceipt":
      return receiptAvailable
        ? {
            blockHash,
            blockNumber: "0x3e6",
            transactionHash: txHash,
            transactionIndex: "0x0",
            from: account,
            to: IMD,
            cumulativeGasUsed: "0x10000",
            gasUsed: "0x10000",
            effectiveGasPrice: "0x1",
            contractAddress: null,
            logsBloom: `0x${"00".repeat(256)}`,
            status: "0x1",
            type: "0x2",
            logs: [
              {
                address: IMD,
                blockHash,
                blockNumber: "0x3e6",
                transactionHash: txHash,
                transactionIndex: "0x0",
                logIndex: "0x0",
                removed: false,
                topics: encodeEventTopics({
                  abi: erc20Abi,
                  eventName: "Transfer",
                  args: {
                    from: account,
                    to: mode === "wrong-recipient" ? BOARD : BURN,
                  },
                }),
                data: encodeAbiParameters([{ type: "uint256" }], [paidAmount]),
              },
            ],
          }
        : null;
    case "eth_call": {
      const args = request.params[0];
      if (args.to.toLowerCase() === BOARD.toLowerCase()) {
        const fn = decodeFunctionData({ abi: boardAbi, data: args.data });
        let result: any;
        switch (fn.functionName) {
          case "latestEpoch":
            result = mode === "empty" ? 0n : mode === "epoch-changed" ? 2n : 1n;
            break;
          case "summary":
            result = [epochData(), mode === "stale", mode !== "configuration"];
            break;
          case "epochTokenPolicies":
            result = [{ token: IMD, supportTarget: 2000n }];
            break;
          case "walletAt":
            result = {
              epoch: 1n,
              asOfBlock: 900n,
              asOfTimestamp: BigInt(Math.floor(Date.now() / 1000) - 60),
              stale: false,
              currentConfiguration: true,
              found: mode !== "not-found",
              tier: 3,
              stats: reportStats,
            };
            break;
          case "walletTokens":
            result = mode === "not-found" ? [] : [observations];
            break;
          case "leaderboard": {
            const offset = Number(fn.args[1]);
            const limit = Number(fn.args[2]);
            leaderCalls.push(offset);
            result = Array.from({ length: limit }, (_, index) => ({
              wallet: `0x${(offset + index + 1).toString(16).padStart(40, "0")}`,
              rank: offset + index + 1,
              score: 9999 - offset - index,
              tier: 3,
              activeSeats: 1,
            }));
            break;
          }
          default:
            throw new Error(`Unexpected board call ${fn.functionName}`);
        }
        return encodeFunctionResult({
          abi: boardAbi,
          functionName: fn.functionName,
          result,
        } as any);
      }
      const fn = decodeFunctionData({ abi: erc20Abi, data: args.data });
      const result =
        fn.functionName === "decimals"
          ? 18
          : fn.functionName === "symbol"
            ? "IMD"
            : fn.functionName === "balanceOf"
              ? mode === "insufficient"
                ? 0n
                : 100n * 10n ** 18n
              : true;
      return encodeFunctionResult({
        abi: erc20Abi,
        functionName: fn.functionName,
        result,
      } as any);
    }
    default:
      throw new Error(`Unexpected RPC method: ${request.method}`);
  }
}
const results: { test: string; passed: boolean; detail?: string }[] = [];
let activePage: any;
async function check(name: string, run: () => Promise<void>) {
  try {
    await run();
    results.push({ test: name, passed: true });
    console.log("PASS", name);
  } catch (error) {
    results.push({ test: name, passed: false, detail: String(error) });
    if (activePage) {
      await activePage.screenshot({
        path: join(output, "failure.png"),
        fullPage: true,
      });
      await writeFile(
        join(output, "failure.txt"),
        await activePage.locator("body").innerText(),
      );
      console.log("Browser errors", errors);
    }
    throw error;
  }
}
let browser: any;
try {
  const type = process.env.IMD_BROWSER === "webkit" ? webkit : chromium;
  browser = await type.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    acceptDownloads: true,
  });
  await context.route("https://**/*", async (route: any) => {
    if (
      ![
        "https://ethereum-rpc.publicnode.com/",
        "https://eth.drpc.org/",
      ].includes(route.request().url())
    ) {
      await route.abort();
      return;
    }
    if (mode === "rpc-error") {
      await route.fulfill({ status: 503, body: "Unavailable" });
      return;
    }
    const requests = JSON.parse(route.request().postData() ?? "{}");
    const respond = (request: any) => ({
      jsonrpc: "2.0",
      id: request.id,
      result: rpcResult(request),
    });
    await route.fulfill({
      json: Array.isArray(requests) ? requests.map(respond) : respond(requests),
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  let page = await context.newPage();
  activePage = page;
  const watch = (target: any) => {
    target.on("pageerror", (error: Error) => errors.push(error.message));
    target.on("console", (message: any) => {
      if (
        message.type() === "error" &&
        !message.location().url.startsWith("https://")
      )
        errors.push(message.text());
    });
    target.on("requestfailed", (request: any) => {
      if (request.url().startsWith(url))
        errors.push(`Failed local resource: ${request.url()}`);
    });
    target.on("response", (response: any) => {
      if (response.url().startsWith(url) && response.status() >= 400)
        errors.push(
          `Local resource HTTP ${response.status()}: ${response.url()}`,
        );
    });
  };
  watch(page);
  await page.goto(url);
  await page.getByText("Awaiting the first snapshot").waitFor();
  await check(
    "Static subpath assets and mobile first-screen action",
    async () => {
      assert.equal(
        await page.title(),
        "IMD ChadBoard · Wallets, ranked by action",
      );
      const box = await page
        .getByRole("button", { name: "Check query", exact: true })
        .boundingBox();
      assert.ok(box && box.y + box.height <= 844, JSON.stringify(box));
      assert.equal(
        await page.locator("link[rel=icon]").getAttribute("href"),
        "./favicon.svg",
      );
      for (const asset of ["share.png", "favicon.svg"])
        assert.equal((await context.request.get(url + asset)).status(), 200);
    },
  );
  await check(
    "Responsive reflow, focus, reduced motion and accessibility",
    async () => {
      for (const width of [320, 390, 820, 1440]) {
        await page.setViewportSize({ width, height: width > 800 ? 1000 : 844 });
        assert.ok(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
        await page.screenshot({
          path: join(output, `empty-${width}.png`),
          fullPage: true,
        });
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await page.getByText("Awaiting the first snapshot").waitFor();
      await page.keyboard.press("Tab");
      assert.equal(await page.locator(":focus").innerText(), "Skip to query");
      await page.keyboard.press("Enter");
      await page.keyboard.press("Tab");
      assert.equal(await page.locator(":focus").innerText(), "Wallets");
      await page.screenshot({ path: join(output, "keyboard-focus.png") });
      await page.emulateMedia({ reducedMotion: "reduce" });
      assert.equal(
        await page
          .getByRole("button", { name: "Check query", exact: true })
          .evaluate((el: Element) => getComputedStyle(el).transitionDuration),
        "0s",
      );
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      await page.screenshot({
        path: join(output, "text-200-percent.png"),
        fullPage: true,
      });
      const overflow = await page.evaluate(() =>
        Array.from(document.querySelectorAll("body *"))
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.right > innerWidth;
          })
          .map((el) => ({
            tag: el.tagName,
            class: el.className,
            text: el.textContent?.slice(0, 60),
            width: el.getBoundingClientRect().width,
          })),
      );
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        JSON.stringify(overflow),
      );
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "";
      });
      if (process.env.IMD_AXE) {
        const { default: AxeBuilder } = await import(
          pathToFileURL(process.env.IMD_AXE).href
        );
        const audit = await new AxeBuilder({ page }).analyze();
        await writeFile(
          join(output, "axe-empty.json"),
          JSON.stringify(audit.violations, null, 2),
        );
        assert.deepEqual(
          audit.violations.map((v: any) => v.id),
          [],
        );
      }
    },
  );
  await check(
    "Invalid input has a focused inline error; valid input cannot pay for missing data",
    async () => {
      await page
        .getByRole("button", { name: "Check query", exact: true })
        .click();
      assert.equal(await page.locator(":focus").getAttribute("id"), "wallets");
      await page
        .getByText("Enter at least one Ethereum wallet address.")
        .waitFor();
      await page.getByLabel("Ethereum wallet addresses").fill(account);
      await page
        .getByRole("button", { name: "Check query", exact: true })
        .click();
      await page.getByText(/No snapshot has been published yet/).waitFor();
      assert.equal(await page.locator("dialog").count(), 0);
    },
  );
  await check(
    "No-wallet dialog has an actionable fallback and restores focus",
    async () => {
      await page
        .getByRole("button", { name: "Connect wallet", exact: true })
        .click();
      await page.getByText(/No browser wallet detected/).waitFor();
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("dialog").count(), 0);
      assert.equal(await page.locator(":focus").innerText(), "Connect wallet");
    },
  );
  await check(
    "All leaderboard pack prices update and radio controls support the keyboard",
    async () => {
      await page
        .getByRole("button", { name: "Leaderboard", exact: true })
        .click();
      for (const [count, price] of [
        [10, "0.1"],
        [50, "0.5"],
        [100, "1"],
        [1000, "2"],
      ]) {
        await page.locator(`input[value="${count}"]`).check();
        assert.equal(await page.locator(".price").innerText(), `${price} IMD`);
      }
      await page.locator('input[value="1000"]').focus();
      await page.keyboard.press("ArrowLeft");
      assert.ok(await page.locator('input[value="100"]').isChecked());
    },
  );
  for (const [state, message] of [
    ["stale", "The latest snapshot is out of date"],
    ["configuration", "The latest snapshot is out of date"],
    ["not-found", "None of these wallets is in the latest snapshot"],
    ["code-mismatch", "The board code could not be verified"],
  ] as const) {
    await check(`No payment when ${state}`, async () => {
      mode = state;
      await page.reload();
      await page.getByLabel("Ethereum wallet addresses").fill(account);
      await page
        .getByRole("button", { name: "Check query", exact: true })
        .click();
      await page
        .locator(".query-notice")
        .filter({ hasText: message })
        .waitFor();
      assert.equal(await page.locator("dialog").count(), 0);
    });
  }
  await check(
    "RPC failure shows unavailable values and refresh recovers",
    async () => {
      mode = "rpc-error";
      await page.reload();
      await page
        .getByText("Could not reach Ethereum", { exact: true })
        .waitFor({ timeout: 60000 });
      assert.equal(
        await page.locator(".board-overview strong").first().innerText(),
        "Unavailable",
      );
      mode = "ready";
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await page.getByText("Snapshot #1 available", { exact: true }).waitFor();
    },
  );
  mode = "ready";
  await context.addInitScript({
    content: await readFile(
      new URL("../tests/fixtures/wallet-provider.js", import.meta.url),
      "utf8",
    ),
  });
  await page.reload();
  await page.getByText("Snapshot #1 available").waitFor();
  await check(
    "Preflight deduplicates wallets, shows exact recipient and requires consent",
    async () => {
      await page
        .getByLabel("Ethereum wallet addresses")
        .fill(`${account},\n${account}`);
      assert.equal(await page.locator(".price").innerText(), "0.1 IMD");
      await page
        .getByRole("button", { name: "Check query", exact: true })
        .click();
      await page.getByRole("heading", { name: "Review your query" }).waitFor();
      await page.locator("dialog").getByText(BURN, { exact: true }).waitFor();
      assert.match(
        await page.locator(".review-details").innerText(),
        /1 ranked \/ 1 requested/,
      );
      await page
        .getByRole("button", { name: "Connect wallet to continue" })
        .click();
      await page.getByRole("button", { name: "Test wallet" }).click();
      await page.getByRole("button", { name: "Switch to Ethereum" }).click();
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .waitFor();
      assert.ok(
        await page
          .getByRole("button", { name: "Send 0.1 IMD & view results" })
          .isDisabled(),
      );
      await page
        .getByLabel("I understand the fee and irreversible transfer.")
        .check();
      await page.screenshot({ path: join(output, "payment-review-mock.png") });
      if (process.env.IMD_AXE) {
        const { default: AxeBuilder } = await import(
          pathToFileURL(process.env.IMD_AXE).href
        );
        const audit = await new AxeBuilder({ page }).analyze();
        await writeFile(
          join(output, "axe-review.json"),
          JSON.stringify(audit.violations, null, 2),
        );
        assert.deepEqual(
          audit.violations.map((v: any) => v.id),
          [],
        );
      }
    },
  );
  await check(
    "Insufficient balance, changed snapshot/account and rejected signature leave the query unpaid",
    async () => {
      mode = "insufficient";
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .click();
      await page.getByText(/insufficient IMD/).waitFor();
      assert.equal(
        await page.evaluate(
          () =>
            (window as any).__wallet.requests.filter(
              (r: any) => r.method === "eth_sendTransaction",
            ).length,
        ),
        0,
      );
      mode = "epoch-changed";
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .click();
      await page
        .getByText(/The snapshot changed or is no longer current/)
        .waitFor();
      mode = "ready";
      await page.evaluate((nextAccount: string) => {
        (window as any).__wallet.account = nextAccount;
      }, BOARD);
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .click();
      await page.getByText(/Your wallet account changed/).waitFor();
      await page.evaluate((originalAccount: string) => {
        (window as any).__wallet.account = originalAccount;
      }, account);
      await page.evaluate(() => {
        (window as any).__wallet.reject = true;
      });
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .click();
      await page.getByText(/You declined the wallet request/).waitFor();
      assert.equal(await page.locator(".results").count(), 0);
    },
  );
  await check(
    "Pending transfer is exact, stored and recovered after a reload without paying twice",
    async () => {
      receiptAvailable = false;
      await page.evaluate(() => {
        (window as any).__wallet.reject = false;
      });
      await page
        .getByRole("button", { name: "Send 0.1 IMD & view results" })
        .click();
      await page
        .getByRole("heading", { name: "Your payment is being tracked" })
        .waitFor();
      const request = await page.evaluate(() =>
        (window as any).__wallet.requests
          .filter((r: any) => r.method === "eth_sendTransaction")
          .at(-1),
      );
      assert.equal(request.params[0].to.toLowerCase(), IMD.toLowerCase());
      assert.equal(request.params[0].value, "0x0");
      const decoded = decodeFunctionData({
        abi: erc20Abi,
        data: request.params[0].data,
      });
      assert.equal(decoded.functionName, "transfer");
      assert.deepEqual(decoded.args, [BURN, 10n ** 17n]);
      assert.ok(
        await page.evaluate(
          () => !!localStorage.getItem("imd-chadboard-pending-v1"),
        ),
      );
      const recoveryDownload = page.waitForEvent("download");
      await page.getByRole("button", { name: "Save recovery file" }).click();
      await (await recoveryDownload).saveAs(join(output, "recovery.json"));
      await page.reload();
      await page
        .getByRole("heading", { name: "Your payment is being tracked" })
        .waitFor();
      assert.ok(
        await page
          .getByRole("button", { name: "Resolve pending payment below" })
          .isDisabled(),
      );
      receiptAvailable = true;
      await page.getByRole("button", { name: "Check payment status" }).click();
      await page.getByRole("heading", { name: "1 wallet results" }).waitFor();
      assert.equal(
        await page.evaluate(() =>
          localStorage.getItem("imd-chadboard-pending-v1"),
        ),
        null,
      );
      assert.equal(
        await page.evaluate(
          () =>
            (window as any).__wallet.requests.filter(
              (r: any) => r.method === "eth_sendTransaction",
            ).length,
        ),
        0,
      );
    },
  );
  await check(
    "Paid results expose metrics, raw token accounting, search, evidence and downloads",
    async () => {
      await page.getByText("View wallet activity", { exact: true }).click();
      await page.getByText("IMD holdings & transfers").click();
      await page.getByText("Claimed rewards", { exact: true }).waitFor();
      await page.getByLabel("Filter these results by address").fill("missing");
      await page.getByRole("button", { name: "Clear filter" }).click();
      await page.getByText("Snapshot evidence & methodology").click();
      await page.getByText("Evidence hash", { exact: true }).waitFor();
      for (const format of ["JSON", "CSV"]) {
        const download = page.waitForEvent("download");
        await page.getByRole("button", { name: `Download ${format}` }).click();
        const file = await download;
        assert.ok(
          file.suggestedFilename().endsWith(`.${format.toLowerCase()}`),
        );
        await file.saveAs(join(output, file.suggestedFilename()));
        const bytes = await readFile(
          join(output, file.suggestedFilename()),
          "utf8",
        );
        if (format === "JSON") {
          const parsed = JSON.parse(bytes);
          assert.equal(parsed.report.rows.length, 1);
          assert.equal(parsed.report.rows[0].wallet, account);
          assert.equal(parsed.report.snapshot.epoch, "1");
        } else {
          assert.ok(bytes.startsWith("wallet,found,rank,score"));
          assert.ok(bytes.includes(account));
        }
      }
      await page.screenshot({
        path: join(output, "wallet-results-mock.png"),
        fullPage: true,
      });
      if (process.env.IMD_AXE) {
        const { default: AxeBuilder } = await import(
          pathToFileURL(process.env.IMD_AXE).href
        );
        const audit = await new AxeBuilder({ page }).analyze();
        await writeFile(
          join(output, "axe-results.json"),
          JSON.stringify(audit.violations, null, 2),
        );
        assert.deepEqual(
          audit.violations.map((v: any) => v.id),
          [],
        );
      }
    },
  );
  await check(
    "Top 1,000 uses ten bounded pages, costs 2 IMD and renders paged results",
    async () => {
      leaderCalls = [];
      paidAmount = 2n * 10n ** 18n;
      await page
        .getByRole("button", { name: "Leaderboard", exact: true })
        .click();
      await page.locator('input[value="1000"]').check();
      await page
        .getByRole("button", { name: "Check query", exact: true })
        .click();
      await page.getByRole("heading", { name: "Review your query" }).waitFor();
      assert.deepEqual(
        leaderCalls,
        [0, 100, 200, 300, 400, 500, 600, 700, 800, 900],
      );
      await page
        .getByLabel("I understand the fee and irreversible transfer.")
        .check();
      await page
        .getByRole("button", { name: "Connect wallet to continue" })
        .click();
      await page.getByRole("button", { name: "Test wallet" }).click();
      await page.getByRole("button", { name: "Switch to Ethereum" }).click();
      await page
        .getByRole("button", { name: "Send 2 IMD & view results" })
        .click();
      await page.getByRole("heading", { name: "Top 1,000 results" }).waitFor();
      assert.equal(await page.locator(".ranking-row").count(), 25);
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await page.getByText("Page 2 of 40", { exact: true }).waitFor();
      assert.equal(
        await page.locator(".ranking-row .rank").first().innerText(),
        "#26",
      );
      for (const width of [320, 390, 820, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        assert.ok(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
      }
      await page.screenshot({
        path: join(output, "leaderboard-results-mock.png"),
        fullPage: true,
      });
    },
  );
  await check(
    "Recovery file import validates content and retrieves a receipt without a new payment",
    async () => {
      paidAmount = 10n ** 17n;
      await page.reload();
      await page
        .getByText("Where are my results saved?", { exact: true })
        .click();
      await page.getByLabel("Restore a saved payment").setInputFiles({
        name: "invalid.json",
        mimeType: "application/json",
        buffer: Buffer.from("{}"),
      });
      await page
        .getByText(/This is not a valid ChadBoard recovery file/)
        .waitFor();
      await page
        .getByLabel("Restore a saved payment")
        .setInputFiles(join(output, "recovery.json"));
      mode = "wrong-recipient";
      await page.getByRole("button", { name: "Check payment status" }).click();
      await page
        .getByText(/No matching IMD transfer to the dead address was found/)
        .waitFor();
      assert.equal(await page.locator(".results").count(), 0);
      mode = "ready";
      await page.getByRole("button", { name: "Check payment status" }).click();
      await page.getByRole("heading", { name: "1 wallet results" }).waitFor();
      assert.equal(
        await page.evaluate(
          () =>
            (window as any).__wallet.requests.filter(
              (r: any) => r.method === "eth_sendTransaction",
            ).length,
        ),
        0,
      );
    },
  );
  await check(
    "No JavaScript exceptions, local console errors or failed local resources",
    async () => {
      assert.deepEqual(errors, []);
    },
  );
  await context.close();
} finally {
  await writeFile(
    join(output, "interaction-results.json"),
    JSON.stringify(
      {
        browser: process.env.IMD_BROWSER ?? "chromium",
        mockData: true,
        tests: results,
        errors,
      },
      null,
      2,
    ),
  );
  await browser?.close();
  server.close();
}
