"""Minimal JSON-RPC client with endpoint rotation, retries and adaptive log ranges."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("chadboard.rpc")


class RpcError(Exception):
    def __init__(self, message: str, code: int | None = None, status: int | None = None, max_range: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.max_range = max_range


RANGE_HINTS = ("range", "limit", "too many", "more than", "exceed", "archive", "timeout", "too large", "cu limit")


def safe_error(error: object) -> str:
    """Provider errors can echo a URL or API key. Retain only diagnostic categories."""
    if isinstance(error, RpcError):
        return str(error)
    return type(error).__name__


def provider_error(message: object) -> str:
    text = str(message).lower()
    if "revert" in text:
        return "RPC execution reverted"
    if any(h in text for h in RANGE_HINTS):
        return "RPC range or rate limit exceeded"
    return "RPC provider rejected request"


class Rpc:
    def __init__(self, urls: list[str], timeout: int = 60, attempts: int = 6):
        if not urls:
            raise ValueError("at least one RPC URL is required")
        self.urls = list(urls)
        self.timeout = timeout
        self.attempts = attempts
        self._cursor = 0
        self._id = 0
        self.requests = 0
        self.log_range_limit: int | None = None

    def _post(self, url: str, method: str, params: list) -> dict:
        self._id += 1
        self.requests += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"content-type": "application/json", "user-agent": "chadboard-indexer/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            # Extract only a numeric range cap, never persist/print the provider body.
            detail = err.read(8192).decode("utf-8", "replace")
            match = re.search(r"up to (?:a )?(\d+) block range", detail)
            cap = int(match[1]) if match else None
            if cap:
                self.log_range_limit = cap
            raise RpcError(f"RPC HTTP {err.code}" + (f"; maximum log range {cap} blocks" if cap else ""), status=err.code, max_range=cap) from None
        if isinstance(payload, dict) and "error" in payload:
            error = payload["error"] or {}
            raise RpcError(provider_error(error.get("message", error)), code=error.get("code"))
        if not isinstance(payload, dict) or "result" not in payload:
            raise RpcError("malformed RPC response")
        return payload["result"]

    def call(self, method: str, params: list, *, rotate_on_error: bool = True) -> object:
        last: Exception | None = None
        for attempt in range(self.attempts):
            url = self.urls[self._cursor % len(self.urls)]
            try:
                return self._post(url, method, params)
            except (RpcError, urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError) as err:
                last = err
                if isinstance(err, RpcError) and "revert" in str(err).lower():
                    raise  # deterministic: retrying cannot help
                log.warning("rpc %s failed (attempt %d): %s", method, attempt + 1, safe_error(err))
                if rotate_on_error:
                    self._cursor += 1
                time.sleep(min(0.5 * 2**attempt, 10))
        raise RpcError(f"{method} failed on every endpoint: {safe_error(last)}") from None

    # Convenience wrappers -------------------------------------------------

    def chain_id(self) -> int:
        return int(self.call("eth_chainId", []), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block(self, number: int | str) -> dict:
        tag = number if isinstance(number, str) else hex(number)
        result = self.call("eth_getBlockByNumber", [tag, False])
        if not result:
            raise RpcError(f"block {tag} not available")
        return result

    def finalized_block(self, confirmations: int) -> dict:
        """Safe observation block: head minus confirmations, never past the finalized tag.

        Development chains report the genesis block as finalized, so a zero result is
        ignored and the confirmation depth alone applies.
        """
        head = self.block_number()
        target = max(0, head - confirmations)
        try:
            finalized = int(self.block("finalized")["number"], 16)
        except RpcError:
            finalized = 0
        if finalized > 0:
            target = min(target, finalized)
        return self.block(target)

    def get_code(self, address: str, block: int | str = "latest") -> str:
        tag = block if isinstance(block, str) else hex(block)
        return self.call("eth_getCode", [address, tag])

    def eth_call(self, to: str, data: str, block: int | str = "latest") -> str:
        tag = block if isinstance(block, str) else hex(block)
        return self.call("eth_call", [{"to": to, "data": data}, tag])

    def get_logs_adaptive(self, address: str, topics: list, from_block: int, to_block: int, chunk: int):
        """Yield (chunk_from, chunk_to, logs) covering [from_block, to_block] in order.

        Range errors shrink the chunk; success slowly grows it again (bounded by the
        configured chunk). Every yielded range is contiguous with the previous one.
        """
        cap = min(chunk, self.log_range_limit or chunk)
        size = max(1, cap)
        start = from_block
        while start <= to_block:
            end = min(start + size - 1, to_block)
            params = [{"address": address, "fromBlock": hex(start), "toBlock": hex(end), "topics": topics}]
            try:
                logs = self._get_logs_once(params)
            except RpcError as err:
                if size > 1 and _looks_like_range_error(err):
                    cap = min(cap, err.max_range or max(1, size // 2))
                    size = max(1, cap)
                    log.info("shrinking log range to %d blocks after: %s", size, str(err)[:120])
                    continue
                raise
            yield start, end, logs
            start = end + 1
            if size < cap:
                size = min(cap, size * 2)

    def _get_logs_once(self, params: list) -> list:
        last: Exception | None = None
        for attempt in range(len(self.urls) * 2):
            url = self.urls[self._cursor % len(self.urls)]
            try:
                result = self._post(url, "eth_getLogs", params)
                if not isinstance(result, list):
                    raise RpcError("eth_getLogs returned a non-list")
                return result
            except (RpcError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
                last = err
                if isinstance(err, RpcError) and err.max_range:
                    raise
                self._cursor += 1
                log.warning("eth_getLogs failed: %s", safe_error(err))
                time.sleep(0.5 * (attempt + 1))
        assert last is not None
        if isinstance(last, RpcError):
            raise last
        raise RpcError(safe_error(last)) from None


def _looks_like_range_error(err: RpcError) -> bool:
    text = str(err).lower()
    return any(h in text for h in RANGE_HINTS) or err.status in (400, 403, 413, 429, 503)


class HistoricalRpc(Rpc):
    """Public RPC for current reads; archive RPC only for old state and event ranges."""
    def __init__(self, cfg, historical_before=None):
        super().__init__(cfg.rpc_urls, cfg.rpc_timeout, cfg.rpc_attempts)
        self.archive = Rpc([cfg.archive_rpc_url], cfg.rpc_timeout, cfg.rpc_attempts) if cfg.archive_rpc_url else None
        self.historical_before = historical_before

    @property
    def total_requests(self):
        return self.requests + (self.archive.requests if self.archive else 0)

    def call(self, method, params, **kwargs):
        if self.archive and method in ("eth_getCode", "eth_call", "eth_getBlockByNumber"):
            tag = params[0] if method == "eth_getBlockByNumber" else params[-1]
            if isinstance(tag, str) and tag.startswith("0x"):
                if self.historical_before is None:
                    self.historical_before = super().block_number() - 512
                if int(tag, 16) < self.historical_before:
                    return self.archive.call(method, params, **kwargs)
        return super().call(method, params, **kwargs)

    def _get_logs_once(self, params):
        # Indexer log queries are deep event scans, never browser/current-balance calls.
        if self.archive:
            return self.archive._get_logs_once(params)
        return super()._get_logs_once(params)
