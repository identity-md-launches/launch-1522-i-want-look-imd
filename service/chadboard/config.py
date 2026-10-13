"""Configuration for the ChadBoard data service.

Every value comes from the environment or the pinned deployment records. The
service never holds signing credentials: publication calldata is produced for
the appointed reporter to submit with their own workflow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Public network facts from .imd/reads/deployment.json and network.json.
BOARD_ADDRESS = "0xd27c1f25427a04db405db956fd8b859a53784f28"
IMD_TOKEN = "0xd34a99bc0f67ae1bbd63c660e6d0b0dd03e263b7"
CHAIN_ID = 1
DEFAULT_RPC_URLS = ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"]

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

SCORE_VERSION = "chadboard-holding-v1"
TIERS = ["Observer", "Contributor", "Chad", "GigaChad"]
YEAR_SECONDS = 365 * 86400


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


@dataclass
class Config:
    db_path: Path = field(default_factory=lambda: Path(_env("CHADBOARD_DB", "service/data/chadboard.sqlite")))
    rpc_urls: list[str] = field(
        default_factory=lambda: [u.strip() for u in _env("CHADBOARD_RPC_URLS", ",".join(DEFAULT_RPC_URLS)).split(",") if u.strip()]
    )
    chain_id: int = field(default_factory=lambda: _env_int("CHADBOARD_CHAIN_ID", CHAIN_ID))
    token: str = field(default_factory=lambda: _env("CHADBOARD_TOKEN", IMD_TOKEN).lower())
    board: str = field(default_factory=lambda: _env("CHADBOARD_BOARD", BOARD_ADDRESS).lower())
    # The seat NFT is an owner-settable board source. When the board has it unset,
    # the operator may supply it here; otherwise the seat census is reported as unavailable.
    seat_nft: str = field(default_factory=lambda: _env("CHADBOARD_SEAT_NFT", "").lower())
    # Activation evidence: "<topic0>:<wallet topic index>" (1..3) or "<topic0>:seat:<seat topic index>".
    # Unset means activation cannot be verified from logs and seat holders are reported as such.
    activation_event: str = field(default_factory=lambda: _env("CHADBOARD_ACTIVATION_EVENT", ""))
    start_block: int = field(default_factory=lambda: _env_int("CHADBOARD_START_BLOCK", 0))
    confirmations: int = field(default_factory=lambda: _env_int("CHADBOARD_CONFIRMATIONS", 64))
    log_chunk: int = field(default_factory=lambda: _env_int("CHADBOARD_LOG_CHUNK", 2000))
    max_blocks_per_run: int = field(default_factory=lambda: _env_int("CHADBOARD_MAX_BLOCKS_PER_RUN", 0))
    interval_seconds: int = field(default_factory=lambda: _env_int("CHADBOARD_INTERVAL_SECONDS", 86400))
    retry_attempts: int = field(default_factory=lambda: _env_int("CHADBOARD_RETRY_ATTEMPTS", 4))
    retry_backoff_seconds: int = field(default_factory=lambda: _env_int("CHADBOARD_RETRY_BACKOFF_SECONDS", 30))
    support_target: int = field(default_factory=lambda: int(_env("CHADBOARD_SUPPORT_TARGET", str(10_000 * 10**18))))
    verify_balances: int = field(default_factory=lambda: _env_int("CHADBOARD_VERIFY_BALANCES", 100))
    host: str = field(default_factory=lambda: _env("CHADBOARD_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("CHADBOARD_PORT", 8787))
    publication_dir: Path = field(default_factory=lambda: Path(_env("CHADBOARD_PUBLICATION_DIR", "service/data/publications")))
    rpc_timeout: int = field(default_factory=lambda: _env_int("CHADBOARD_RPC_TIMEOUT", 60))
    rpc_attempts: int = field(default_factory=lambda: _env_int("CHADBOARD_RPC_ATTEMPTS", 5))
    # Never included in API metadata, logs or frontend configuration.
    archive_rpc_url: str = field(default_factory=lambda: _env("ETH_ARCHIVE_RPC_URL", ""), repr=False)
    radar_enabled: bool = field(default_factory=lambda: _env("CHADBOARD_RADAR_ENABLED", "0") == "1")
    radar_ttl: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_TTL_SECONDS", 900))
    radar_max_age: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_MAX_AGE_SECONDS", 86400))
    radar_timeout: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_TIMEOUT", 8))
    radar_budget_seconds: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_BUDGET_SECONDS", 60))
    radar_seat_limit: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_SEAT_LIMIT", 2048))
    radar_min_liquidity_usd: int = field(default_factory=lambda: _env_int("CHADBOARD_RADAR_MIN_LIQUIDITY_USD", 2000))

    def activation_spec(self) -> dict | None:
        if not self.activation_event:
            return None
        parts = self.activation_event.split(":")
        topic = parts[0].lower()
        if len(topic) != 66 or not topic.startswith("0x"):
            raise ValueError("CHADBOARD_ACTIVATION_EVENT must start with a 32-byte topic0")
        if len(parts) == 2:
            return {"topic0": topic, "wallet_topic": int(parts[1])}
        if len(parts) == 3 and parts[1] == "seat":
            return {"topic0": topic, "seat_topic": int(parts[2])}
        raise ValueError("CHADBOARD_ACTIVATION_EVENT must be '<topic0>:<walletTopic>' or '<topic0>:seat:<seatTopic>'")
