import type { Address, Hex } from "viem";

// Public network facts from the pinned deployment.json and network.json.
export const BOARD: Address = "0xd27c1f25427a04db405db956fd8b859a53784f28";
export const IMD: Address = "0xd34a99bc0f67ae1bbd63c660e6d0b0dd03e263b7";
// Explicitly supplied by the requester for this website.
export const BURN: Address = "0x000000000000000000000000000000000000dEaD";
export const CHAIN_ID = 1;
export const EXPLORER = "https://etherscan.io";
export const RPC_URLS = [
  "https://ethereum-rpc.publicnode.com",
  "https://eth.drpc.org",
] as const;
export const BOARD_RUNTIME_HASH: Hex =
  "0xc671c848cccbc703c054231199de354a6fdf48b90c39b0154979772711ae740b";
export const ABI_HASH =
  "0x9890f956e09de6e033bcf8c2637ffea83209159f5c1627f59822906de5e21ad8";
export const SOURCE_COMMIT = "061eccd99cb9b1cd380ea1f0a7f76231fd308bde";
