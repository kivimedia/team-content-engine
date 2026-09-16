"""Shared helpers for evidence collectors: time bounds, hashing, bounded HTTP retries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

Sleep = Callable[[float], Awaitable[None]]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def maybe_await(value: Any) -> None:
    """Callbacks may be plain functions or coroutines (to flush activity to the DB)."""
    if inspect.isawaitable(value):
        await value


class EvidenceHTTPError(RuntimeError):
    """A request that could not be completed after bounded retries."""

    def __init__(self, status: int | None, reason: str) -> None:
        super().__init__(f"{status}: {reason}" if status else reason)
        self.status = status
        self.reason = reason


def as_utc(dt: datetime) -> datetime:
    """Return a tz-aware UTC datetime (naive input is treated as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_db(dt: datetime | None) -> datetime | None:
    """DB columns are naive UTC."""
    if dt is None:
        return None
    return as_utc(dt).replace(tzinfo=None)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def iso_z(dt: datetime) -> str:
    return as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def in_window(dt: datetime | None, start: datetime, end: datetime) -> bool:
    """Half-open window [start, end) with explicit tz-aware comparison."""
    if dt is None:
        return False
    return as_utc(start) <= as_utc(dt) < as_utc(end)


def stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def retry_after_seconds(resp: httpx.Response, now: datetime | None = None) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    now = now or datetime.now(UTC)
    return max(0.0, (as_utc(when) - now).total_seconds())


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_backoff_s: float = 2.0
    max_wait_s: float = 120.0


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    policy: RetryPolicy | None = None,
    sleep: Sleep = asyncio.sleep,
    extra_wait: Callable[[httpx.Response], float | None] | None = None,
    on_wait: Callable[[str], Any] | None = None,
) -> httpx.Response:
    """Send a request, retrying 429/5xx/transport errors a bounded number of times.

    Honors Retry-After. `extra_wait(resp)` lets a caller signal a wait for statuses
    that are not normally retryable (GitHub's 403 rate limit). A wait longer than
    `policy.max_wait_s` is not slept: it raises instead, so the caller records it.
    Returns the final response for non-retryable statuses (the caller classifies).
    """
    policy = policy or RetryPolicy()
    last_reason = "no attempt"
    for attempt in range(1, policy.max_attempts + 1):
        try:
            resp = await client.request(method, url, params=params, headers=headers)
        except httpx.TransportError as exc:
            last_reason = f"transport error: {type(exc).__name__}"
            if attempt == policy.max_attempts:
                raise EvidenceHTTPError(None, last_reason) from exc
            wait = min(policy.base_backoff_s * 2 ** (attempt - 1), policy.max_wait_s)
            if on_wait:
                await maybe_await(on_wait(f"{last_reason}, retry {attempt} in {wait:.0f}s"))
            await sleep(wait)
            continue

        wait: float | None = None
        if extra_wait is not None:
            wait = extra_wait(resp)
        if wait is None and resp.status_code in RETRYABLE_STATUS:
            wait = retry_after_seconds(resp)
            if wait is None:
                wait = policy.base_backoff_s * 2 ** (attempt - 1)
        if wait is None:
            return resp

        last_reason = f"HTTP {resp.status_code}"
        if attempt == policy.max_attempts:
            raise EvidenceHTTPError(
                resp.status_code, f"{last_reason} after {attempt} attempts"
            )
        if wait > policy.max_wait_s:
            raise EvidenceHTTPError(
                resp.status_code,
                f"{last_reason}: required wait {wait:.0f}s exceeds limit {policy.max_wait_s:.0f}s",
            )
        if on_wait:
            await maybe_await(on_wait(f"{last_reason}, waiting {wait:.0f}s (retry {attempt})"))
        await sleep(wait)
    raise EvidenceHTTPError(None, last_reason)
