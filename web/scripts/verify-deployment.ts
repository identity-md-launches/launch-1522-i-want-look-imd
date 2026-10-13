// Read-only verification. An optional --rpc URL supports operator-owned local relays.
// No signing or transaction creation occurs; the RPC URL is never printed.
import assert from "node:assert/strict";
import {
  createPublicClient,
  erc20Abi,
  http,
  keccak256,
  stringToHex,
} from "viem";
import { mainnet } from "viem/chains";
import { boardAbi } from "../src/board-abi";
import {
  ABI_HASH,
  BOARD,
  BOARD_RUNTIME_HASH,
  IMD,
  RPC_URLS,
  SOURCE_COMMIT,
} from "../src/config";
const rpcAt = process.argv.indexOf("--rpc");
const rpc = rpcAt >= 0 ? process.argv[rpcAt + 1] : RPC_URLS[0];
if (!rpc) throw new Error("Supply a URL after --rpc.");
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
const abiHash = keccak256(stringToHex(canonical(boardAbi)));
assert.equal(abiHash, ABI_HASH, "ABI differs from the pinned deployment");
const client = createPublicClient({
  chain: mainnet,
  transport: http(rpc, { timeout: 15_000 }),
});
const blockNumber = await client.getBlockNumber();
const [chainId, code, tokenCode, decimals, symbol, latestEpoch, configuration] =
  await Promise.all([
    client.getChainId(),
    client.getCode({ address: BOARD, blockNumber }),
    client.getCode({ address: IMD, blockNumber }),
    client.readContract({
      address: IMD,
      abi: erc20Abi,
      functionName: "decimals",
      blockNumber,
    }),
    client.readContract({
      address: IMD,
      abi: erc20Abi,
      functionName: "symbol",
      blockNumber,
    }),
    client.readContract({
      address: BOARD,
      abi: boardAbi,
      functionName: "latestEpoch",
      blockNumber,
    }),
    client.readContract({
      address: BOARD,
      abi: boardAbi,
      functionName: "configuration",
      blockNumber,
    }),
  ]);
assert.equal(chainId, 1);
assert.ok(code);
assert.equal(keccak256(code), BOARD_RUNTIME_HASH);
assert.ok(tokenCode && tokenCode !== "0x");
assert.equal(decimals, 18);
assert.equal(symbol, "IMD");
console.log(
  JSON.stringify(
    {
      verifiedAt: new Date().toISOString(),
      sourceCommit: SOURCE_COMMIT,
      source: RPC_URLS[0],
      chainId,
      blockNumber: blockNumber.toString(),
      board: BOARD,
      abiHash,
      runtimeHash: keccak256(code),
      runtimeBytes: (code.length - 2) / 2,
      token: IMD,
      decimals,
      symbol,
      latestEpoch: latestEpoch.toString(),
      configuration: configuration.toString(),
      transactionsSent: 0,
    },
    null,
    2,
  ),
);
