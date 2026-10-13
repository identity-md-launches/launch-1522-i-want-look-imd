// Generated from src/IMDChadBoard.sol at pinned commit 061eccd99cb9b1cd380ea1f0a7f76231fd308bde.
export const boardAbi = [
  {
    type: "constructor",
    inputs: [
      {
        name: "initialOwner",
        type: "address",
        internalType: "address",
      },
    ],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "CLAIM_WINDOW",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint256",
        internalType: "uint256",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "MAX_BATCH",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint256",
        internalType: "uint256",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "MAX_PAGE",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint256",
        internalType: "uint256",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "MAX_TOKENS",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint256",
        internalType: "uint256",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "abortEpoch",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "acceptOwnership",
    inputs: [],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "appendWallets",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
      {
        name: "reports",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.WalletReport[]",
        components: [
          {
            name: "wallet",
            type: "address",
            internalType: "address",
          },
          {
            name: "metrics",
            type: "tuple",
            internalType: "struct IMDChadBoard.WalletMetrics",
            components: [
              {
                name: "activeSeats",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "launches",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "eligibleClaims",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "claimedClaims",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "totalClaimDelay",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "maxClaimDelay",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "interactions",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "distinctApps",
                type: "uint16",
                internalType: "uint16",
              },
            ],
          },
          {
            name: "tokens",
            type: "tuple[]",
            internalType: "struct IMDChadBoard.TokenReport[]",
            components: [
              {
                name: "claimed",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "bought",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "sold",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "otherOut",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "rewardHeld",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "rewardSold",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "rewardOtherOut",
                type: "uint128",
                internalType: "uint128",
              },
              {
                name: "balance",
                type: "uint128",
                internalType: "uint128",
              },
            ],
          },
        ],
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "beginEpoch",
    inputs: [
      {
        name: "snapshot",
        type: "tuple",
        internalType: "struct IMDChadBoard.SnapshotInput",
        components: [
          {
            name: "blockNumber",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "timestamp",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "blockHash",
            type: "bytes32",
            internalType: "bytes32",
          },
          {
            name: "totalSeats",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "activatedSeats",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "walletCount",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "evidenceHash",
            type: "bytes32",
            internalType: "bytes32",
          },
          {
            name: "configuration",
            type: "uint64",
            internalType: "uint64",
          },
        ],
      },
    ],
    outputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "configuration",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "epochCount",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "epochTokenPolicies",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    outputs: [
      {
        name: "",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.TokenPolicy[]",
        components: [
          {
            name: "token",
            type: "address",
            internalType: "address",
          },
          {
            name: "supportTarget",
            type: "uint128",
            internalType: "uint128",
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "finalizeEpoch",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "getEpoch",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    outputs: [
      {
        name: "",
        type: "tuple",
        internalType: "struct IMDChadBoard.Epoch",
        components: [
          {
            name: "status",
            type: "uint8",
            internalType: "enum IMDChadBoard.Status",
          },
          {
            name: "snapshot",
            type: "tuple",
            internalType: "struct IMDChadBoard.SnapshotInput",
            components: [
              {
                name: "blockNumber",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "timestamp",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "blockHash",
                type: "bytes32",
                internalType: "bytes32",
              },
              {
                name: "totalSeats",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "activatedSeats",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "walletCount",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "evidenceHash",
                type: "bytes32",
                internalType: "bytes32",
              },
              {
                name: "configuration",
                type: "uint64",
                internalType: "uint64",
              },
            ],
          },
          {
            name: "configuration",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "maxAge",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "publishedAt",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "seatsWritten",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "walletsWritten",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "reporter",
            type: "address",
            internalType: "address",
          },
          {
            name: "seatNFT",
            type: "address",
            internalType: "address",
          },
          {
            name: "methodologyHash",
            type: "bytes32",
            internalType: "bytes32",
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "latestEpoch",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "leaderboard",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
      {
        name: "offset",
        type: "uint32",
        internalType: "uint32",
      },
      {
        name: "limit",
        type: "uint32",
        internalType: "uint32",
      },
    ],
    outputs: [
      {
        name: "page",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.Leader[]",
        components: [
          {
            name: "wallet",
            type: "address",
            internalType: "address",
          },
          {
            name: "rank",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "score",
            type: "uint16",
            internalType: "uint16",
          },
          {
            name: "tier",
            type: "uint8",
            internalType: "enum IMDChadBoard.Tier",
          },
          {
            name: "activeSeats",
            type: "uint32",
            internalType: "uint32",
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "maxAge",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "methodologyHash",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "bytes32",
        internalType: "bytes32",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "owner",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "address",
        internalType: "address",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "pendingEpoch",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "pendingOwner",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "address",
        internalType: "address",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "previewScore",
    inputs: [
      {
        name: "metrics",
        type: "tuple",
        internalType: "struct IMDChadBoard.WalletMetrics",
        components: [
          {
            name: "activeSeats",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "launches",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "eligibleClaims",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "claimedClaims",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "totalClaimDelay",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "maxClaimDelay",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "interactions",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "distinctApps",
            type: "uint16",
            internalType: "uint16",
          },
        ],
      },
      {
        name: "tokens",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.TokenReport[]",
        components: [
          {
            name: "claimed",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "bought",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "sold",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "otherOut",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardHeld",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardSold",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardOtherOut",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "balance",
            type: "uint128",
            internalType: "uint128",
          },
        ],
      },
    ],
    outputs: [
      {
        name: "score",
        type: "uint16",
        internalType: "uint16",
      },
      {
        name: "retentionBps",
        type: "uint16",
        internalType: "uint16",
      },
      {
        name: "supportBps",
        type: "uint16",
        internalType: "uint16",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "reporter",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "address",
        internalType: "address",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "seatNFT",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "address",
        internalType: "address",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "setMaxAge",
    inputs: [
      {
        name: "seconds_",
        type: "uint64",
        internalType: "uint64",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "setReporter",
    inputs: [
      {
        name: "nextReporter",
        type: "address",
        internalType: "address",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "setSources",
    inputs: [
      {
        name: "nft",
        type: "address",
        internalType: "address",
      },
      {
        name: "policyHash",
        type: "bytes32",
        internalType: "bytes32",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "setTokenPolicies",
    inputs: [
      {
        name: "policies",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.TokenPolicy[]",
        components: [
          {
            name: "token",
            type: "address",
            internalType: "address",
          },
          {
            name: "supportTarget",
            type: "uint128",
            internalType: "uint128",
          },
        ],
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "summary",
    inputs: [],
    outputs: [
      {
        name: "epoch",
        type: "tuple",
        internalType: "struct IMDChadBoard.Epoch",
        components: [
          {
            name: "status",
            type: "uint8",
            internalType: "enum IMDChadBoard.Status",
          },
          {
            name: "snapshot",
            type: "tuple",
            internalType: "struct IMDChadBoard.SnapshotInput",
            components: [
              {
                name: "blockNumber",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "timestamp",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "blockHash",
                type: "bytes32",
                internalType: "bytes32",
              },
              {
                name: "totalSeats",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "activatedSeats",
                type: "uint64",
                internalType: "uint64",
              },
              {
                name: "walletCount",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "evidenceHash",
                type: "bytes32",
                internalType: "bytes32",
              },
              {
                name: "configuration",
                type: "uint64",
                internalType: "uint64",
              },
            ],
          },
          {
            name: "configuration",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "maxAge",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "publishedAt",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "seatsWritten",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "walletsWritten",
            type: "uint32",
            internalType: "uint32",
          },
          {
            name: "reporter",
            type: "address",
            internalType: "address",
          },
          {
            name: "seatNFT",
            type: "address",
            internalType: "address",
          },
          {
            name: "methodologyHash",
            type: "bytes32",
            internalType: "bytes32",
          },
        ],
      },
      {
        name: "stale",
        type: "bool",
        internalType: "bool",
      },
      {
        name: "currentConfiguration",
        type: "bool",
        internalType: "bool",
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "tierFor",
    inputs: [
      {
        name: "score",
        type: "uint16",
        internalType: "uint16",
      },
    ],
    outputs: [
      {
        name: "",
        type: "uint8",
        internalType: "enum IMDChadBoard.Tier",
      },
    ],
    stateMutability: "pure",
  },
  {
    type: "function",
    name: "tokenPolicies",
    inputs: [],
    outputs: [
      {
        name: "",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.TokenPolicy[]",
        components: [
          {
            name: "token",
            type: "address",
            internalType: "address",
          },
          {
            name: "supportTarget",
            type: "uint128",
            internalType: "uint128",
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "transferOwnership",
    inputs: [
      {
        name: "nextOwner",
        type: "address",
        internalType: "address",
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "walletAt",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
      {
        name: "wallet",
        type: "address",
        internalType: "address",
      },
    ],
    outputs: [
      {
        name: "rating",
        type: "tuple",
        internalType: "struct IMDChadBoard.Rating",
        components: [
          {
            name: "epoch",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "asOfBlock",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "asOfTimestamp",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "stale",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "currentConfiguration",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "found",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "tier",
            type: "uint8",
            internalType: "enum IMDChadBoard.Tier",
          },
          {
            name: "stats",
            type: "tuple",
            internalType: "struct IMDChadBoard.WalletStats",
            components: [
              {
                name: "metrics",
                type: "tuple",
                internalType: "struct IMDChadBoard.WalletMetrics",
                components: [
                  {
                    name: "activeSeats",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "launches",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "eligibleClaims",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "claimedClaims",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "totalClaimDelay",
                    type: "uint64",
                    internalType: "uint64",
                  },
                  {
                    name: "maxClaimDelay",
                    type: "uint64",
                    internalType: "uint64",
                  },
                  {
                    name: "interactions",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "distinctApps",
                    type: "uint16",
                    internalType: "uint16",
                  },
                ],
              },
              {
                name: "rank",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "score",
                type: "uint16",
                internalType: "uint16",
              },
              {
                name: "retentionBps",
                type: "uint16",
                internalType: "uint16",
              },
              {
                name: "supportBps",
                type: "uint16",
                internalType: "uint16",
              },
            ],
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "walletRating",
    inputs: [
      {
        name: "wallet",
        type: "address",
        internalType: "address",
      },
    ],
    outputs: [
      {
        name: "",
        type: "tuple",
        internalType: "struct IMDChadBoard.Rating",
        components: [
          {
            name: "epoch",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "asOfBlock",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "asOfTimestamp",
            type: "uint64",
            internalType: "uint64",
          },
          {
            name: "stale",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "currentConfiguration",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "found",
            type: "bool",
            internalType: "bool",
          },
          {
            name: "tier",
            type: "uint8",
            internalType: "enum IMDChadBoard.Tier",
          },
          {
            name: "stats",
            type: "tuple",
            internalType: "struct IMDChadBoard.WalletStats",
            components: [
              {
                name: "metrics",
                type: "tuple",
                internalType: "struct IMDChadBoard.WalletMetrics",
                components: [
                  {
                    name: "activeSeats",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "launches",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "eligibleClaims",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "claimedClaims",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "totalClaimDelay",
                    type: "uint64",
                    internalType: "uint64",
                  },
                  {
                    name: "maxClaimDelay",
                    type: "uint64",
                    internalType: "uint64",
                  },
                  {
                    name: "interactions",
                    type: "uint32",
                    internalType: "uint32",
                  },
                  {
                    name: "distinctApps",
                    type: "uint16",
                    internalType: "uint16",
                  },
                ],
              },
              {
                name: "rank",
                type: "uint32",
                internalType: "uint32",
              },
              {
                name: "score",
                type: "uint16",
                internalType: "uint16",
              },
              {
                name: "retentionBps",
                type: "uint16",
                internalType: "uint16",
              },
              {
                name: "supportBps",
                type: "uint16",
                internalType: "uint16",
              },
            ],
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "function",
    name: "walletTokens",
    inputs: [
      {
        name: "id",
        type: "uint64",
        internalType: "uint64",
      },
      {
        name: "wallet",
        type: "address",
        internalType: "address",
      },
    ],
    outputs: [
      {
        name: "",
        type: "tuple[]",
        internalType: "struct IMDChadBoard.TokenReport[]",
        components: [
          {
            name: "claimed",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "bought",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "sold",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "otherOut",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardHeld",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardSold",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "rewardOtherOut",
            type: "uint128",
            internalType: "uint128",
          },
          {
            name: "balance",
            type: "uint128",
            internalType: "uint128",
          },
        ],
      },
    ],
    stateMutability: "view",
  },
  {
    type: "event",
    name: "EpochAborted",
    inputs: [
      {
        name: "epoch",
        type: "uint64",
        indexed: true,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "EpochPublished",
    inputs: [
      {
        name: "epoch",
        type: "uint64",
        indexed: true,
        internalType: "uint64",
      },
      {
        name: "wallets",
        type: "uint32",
        indexed: false,
        internalType: "uint32",
      },
      {
        name: "activatedSeats",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "EpochStarted",
    inputs: [
      {
        name: "epoch",
        type: "uint64",
        indexed: true,
        internalType: "uint64",
      },
      {
        name: "asOfBlock",
        type: "uint64",
        indexed: true,
        internalType: "uint64",
      },
      {
        name: "evidenceHash",
        type: "bytes32",
        indexed: false,
        internalType: "bytes32",
      },
      {
        name: "configuration",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "MaxAgeSet",
    inputs: [
      {
        name: "maxAge",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
      {
        name: "configuration",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "OwnershipTransferStarted",
    inputs: [
      {
        name: "owner",
        type: "address",
        indexed: true,
        internalType: "address",
      },
      {
        name: "pendingOwner",
        type: "address",
        indexed: true,
        internalType: "address",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "OwnershipTransferred",
    inputs: [
      {
        name: "previousOwner",
        type: "address",
        indexed: true,
        internalType: "address",
      },
      {
        name: "owner",
        type: "address",
        indexed: true,
        internalType: "address",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "ReporterSet",
    inputs: [
      {
        name: "reporter",
        type: "address",
        indexed: true,
        internalType: "address",
      },
      {
        name: "configuration",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "SourcesSet",
    inputs: [
      {
        name: "seatNFT",
        type: "address",
        indexed: true,
        internalType: "address",
      },
      {
        name: "methodologyHash",
        type: "bytes32",
        indexed: false,
        internalType: "bytes32",
      },
      {
        name: "configuration",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "TokenPoliciesSet",
    inputs: [
      {
        name: "policiesHash",
        type: "bytes32",
        indexed: false,
        internalType: "bytes32",
      },
      {
        name: "configuration",
        type: "uint64",
        indexed: false,
        internalType: "uint64",
      },
    ],
    anonymous: false,
  },
  {
    type: "event",
    name: "WalletAppended",
    inputs: [
      {
        name: "epoch",
        type: "uint64",
        indexed: true,
        internalType: "uint64",
      },
      {
        name: "wallet",
        type: "address",
        indexed: true,
        internalType: "address",
      },
      {
        name: "rank",
        type: "uint32",
        indexed: false,
        internalType: "uint32",
      },
      {
        name: "score",
        type: "uint16",
        indexed: false,
        internalType: "uint16",
      },
    ],
    anonymous: false,
  },
  {
    type: "error",
    name: "BlockHashMismatch",
    inputs: [],
  },
  {
    type: "error",
    name: "DuplicateWallet",
    inputs: [],
  },
  {
    type: "error",
    name: "IncompleteSnapshot",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidAddress",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidBatch",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidConfiguration",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidEpoch",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidMetrics",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidOrder",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidPage",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidSnapshot",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidTokenReport",
    inputs: [],
  },
  {
    type: "error",
    name: "InvalidWallet",
    inputs: [],
  },
  {
    type: "error",
    name: "NoPublishedEpoch",
    inputs: [],
  },
  {
    type: "error",
    name: "NotConfigured",
    inputs: [],
  },
  {
    type: "error",
    name: "PendingEpoch",
    inputs: [],
  },
  {
    type: "error",
    name: "SnapshotTooOld",
    inputs: [],
  },
  {
    type: "error",
    name: "Unauthorized",
    inputs: [],
  },
] as const;
