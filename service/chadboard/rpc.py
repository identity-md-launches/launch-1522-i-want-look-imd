"""Minimal JSON-RPC client with endpoint rotation, retries and adaptive log ranges."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("chadboard.rpc")


class RpcError(Exception):
    def __init__(self, message: str, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


RANGE_HINTS = ("range", "limit", "too many", "more than", "exceed", "archive", "timeout", "too large", "cu limit")


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
            detail = err.read()[:400].decode("utf-8", "replace")
            raise RpcError(f"HTTP {err.code} from {url}: {detail}", status=err.code) from None
        if isinstance(payload, dict) and "error" in payload:
            error = payload["error"] or {}
            raise RpcError(str(error.get("message", error)), code=error.get("code"))
        if not isinstance(payload, dict) or "result" not in payload:
            raise RpcError(f"malformed response from {url}: {str(payload)[:200]}")
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
                log.warning("rpc %s failed on %s (attempt %d): %s", method, url, attempt + 1, str(err)[:160])
                if rotate_on_error:
                    self._cursor += 1
                time.sleep(min(0.5 * 2**attempt, 10))
        raise RpcError(f"{method} failed on every endpoint: {last}")

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
        size = max(1, chunk)
        start = from_block
        while start <= to_block:
            end = min(start + size - 1, to_block)
            params = [{"address": address, "fromBlock": hex(start), "toBlock": hex(end), "topics": topics}]
            try:
                logs = self._get_logs_once(params)
            except RpcError as err:
                if size > 1 and _looks_like_range_error(err):
                    size = max(1, size // 2)
                    log.info("shrinking log range to %d blocks after: %s", size, str(err)[:120])
                    continue
                raise
            yield start, end, logs
            start = end + 1
            if size < chunk:
                size = min(chunk, size * 2)

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
                self._cursor += 1
                log.warning("eth_getLogs failed on %s: %s", url, str(err)[:160])
                time.sleep(0.5 * (attempt + 1))
        assert last is not None
        if isinstance(last, RpcError):
            raise last
        raise RpcError(str(last))


def _looks_like_range_error(err: RpcError) -> bool:
    text = str(err).lower()
    return any(h in text for h in RANGE_HINTS) or err.status in (400, 403, 413, 429, 503)
