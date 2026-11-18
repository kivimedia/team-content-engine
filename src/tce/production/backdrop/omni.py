"""The paid model. Gemini Omni redraws one scene; a Gemini flash model looks at the result.

Standard library only (this runs under the engine's Python). The key travels in a header and
only to Google's API host; it is never put in a URL, a message or a log line.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://generativelanguage.googleapis.com"
# Dollars per million tokens, Google's price list read on 18-Nov-2026.
USD_PER_M_OUT = 12.0
USD_PER_M_IN = 1.5
# What a second of scene costs all in, measured on real scenes (uploaded clip + stills + the
# redrawn video). Used to hold the spend limit BEFORE a call is made; the bill is counted from
# the tokens the answer reports.
USD_PER_S = {"720p": 0.079, "1080p": 0.114, "4k": 0.23}
# The look at a finished scene (a few small stills to a flash model): an upper estimate.
LOOK_USD = 0.01


class OmniError(RuntimeError):
    """The model or the network did not give a usable answer."""


def cost_usd(usage: dict[str, Any] | None) -> float:
    usage = usage or {}
    out = int(usage.get("total_output_tokens") or 0) + int(usage.get("total_thought_tokens") or 0)
    spent = out * USD_PER_M_OUT + int(usage.get("total_input_tokens") or 0) * USD_PER_M_IN
    return round(spent / 1e6, 4)


def estimate_usd(seconds: float, resolution: str) -> float:
    return round(seconds * USD_PER_S.get(resolution, USD_PER_S["1080p"]), 4)


class Api:
    def __init__(
        self, key: str, *, base: str = BASE, timeout_s: float = 600.0, sleep=time.sleep
    ) -> None:
        if not key:
            raise OmniError("no key for the video model")
        self._key = key
        self._base = base.rstrip("/")
        self._timeout = timeout_s
        self._sleep = sleep

    # ------------------------------------------------------------------ http
    def _call(
        self,
        what: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        keyed: bool = True,
        timeout: float | None = None,
    ) -> tuple[bytes, Any]:
        if keyed and not url.startswith(self._base + "/"):
            raise OmniError(f"{what}: refused to send the key to another host")
        sent = dict(headers or {})
        if keyed:
            sent["x-goog-api-key"] = self._key
        req = urllib.request.Request(url, data=body, method=method, headers=sent)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self._timeout) as res:  # noqa: S310
                return res.read(), res.headers
        except urllib.error.HTTPError as exc:
            detail = " ".join(exc.read()[:300].decode("utf-8", "replace").split())
            raise OmniError(f"{what}: HTTP {exc.code} {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OmniError(f"{what}: {type(exc).__name__}") from None

    def _json(
        self, what: str, method: str, url: str, payload: Any = None, **kw: Any
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        raw, _ = self._call(what, method, url, headers=headers, body=body, **kw)
        try:
            return json.loads(raw)
        except ValueError:
            raise OmniError(f"{what}: the answer was not JSON") from None

    # ----------------------------------------------------------------- files
    def upload(self, path: str | Path, mime: str | None = None) -> str:
        """The file's address on Google's side, once it is ready to be used."""
        path = Path(path)
        mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        _, headers = self._call(
            "upload",
            "POST",
            f"{self._base}/upload/v1beta/files",
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                "X-Goog-Upload-Header-Content-Type": mime,
                "Content-Type": "application/json",
            },
            body=json.dumps({"file": {"display_name": path.name}}).encode(),
        )
        target = headers.get("X-Goog-Upload-URL")
        if not target or not target.startswith("https://"):
            raise OmniError("upload: no upload address came back")
        raw, _ = self._call(
            "upload",
            "POST",
            target,
            keyed=False,
            body=data,
            headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
        )
        try:
            info = json.loads(raw)["file"]
        except (ValueError, KeyError, TypeError):
            raise OmniError("upload: the answer named no file") from None
        for _ in range(90):
            if info.get("state") == "ACTIVE":
                return str(info["uri"])
            if info.get("state") == "FAILED":
                break
            self._sleep(2)
            info = self._json("upload", "GET", f"{self._base}/v1beta/{info['name']}")
        raise OmniError(f"upload: {path.name} never became ready")

    # ------------------------------------------------------------------ edit
    def edit(
        self,
        video_uri: str,
        ref_uris: list[str],
        prompt: str,
        *,
        model: str,
        resolution: str,
        out: str | Path,
    ) -> dict[str, Any]:
        """One scene redrawn into ``out``. Returns the usage the bill is counted from."""
        parts: list[dict[str, str]] = [{"type": "video", "uri": video_uri}]
        parts += [{"type": "image", "uri": uri} for uri in ref_uris]
        parts.append({"type": "text", "text": prompt})
        answer = self._json(
            "edit",
            "POST",
            f"{self._base}/v1beta/interactions",
            {
                "model": model,
                "input": parts,
                "response_format": {
                    "type": "video",
                    "aspect_ratio": "9:16",
                    "resolution": resolution,
                    "delivery": "uri",
                },
            },
        )
        video = None
        for step in answer.get("steps") or []:
            for part in step.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "video":
                    video = part
        if video is None:
            why = str(answer.get("status") or answer.get("error") or "no video in the answer")[:200]
            raise OmniError(f"edit: {why}")
        out = Path(out)
        if video.get("data"):
            out.write_bytes(base64.b64decode(video["data"]))
        else:
            found = re.search(r"files/([A-Za-z0-9_-]+)", str(video.get("uri") or ""))
            if not found:
                raise OmniError("edit: the answer named no file")
            url = f"{self._base}/v1beta/files/{found.group(1)}:download?alt=media"
            last = "no answer"
            for _ in range(40):
                try:
                    data, _ = self._call("download", "GET", url)
                    out.write_bytes(data)
                    break
                except OmniError as exc:  # the file can take a few seconds to be there
                    last = str(exc)
                    self._sleep(3)
            else:
                raise OmniError(last)
        if not out.exists() or out.stat().st_size < 10_000:
            raise OmniError("edit: the video that came back is empty")
        return dict(answer.get("usage") or {})

    # ------------------------------------------------------------------ look
    def look(self, model: str, images: list[bytes], prompt: str) -> dict[str, Any]:
        """A flash model's answer, as JSON, about a handful of stills."""
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts += [
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(i).decode()}}
            for i in images
        ]
        answer = self._json(
            "look",
            "POST",
            f"{self._base}/v1beta/models/{model}:generateContent",
            {
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=120,
        )
        try:
            text = "".join(p.get("text", "") for p in answer["candidates"][0]["content"]["parts"])
            found = json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError):
            raise OmniError("look: no readable answer") from None
        if not isinstance(found, dict):
            raise OmniError("look: no readable answer")
        return found
