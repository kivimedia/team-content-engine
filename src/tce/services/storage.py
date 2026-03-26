"""S3-compatible object storage service (PRD Section 23.1)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import structlog

from tce.settings import settings

logger = structlog.get_logger()


class StorageService:
    """Upload and retrieve files from S3-compatible storage."""

    def __init__(
        self,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.endpoint = (endpoint or settings.s3_endpoint).rstrip("/")
        self.bucket = bucket or settings.s3_bucket
        self.access_key = access_key or settings.s3_access_key
        self.secret_key = secret_key or settings.s3_secret_key

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.access_key and self.secret_key)

    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload bytes to S3 bucket under the given key.

        Returns dict with url, key, size_bytes, content_type.
        """
        if not self.configured:
            logger.warning("storage.not_configured", key=key)
            return {"status": "skipped", "reason": "S3 not configured", "key": key}

        url = f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"
        headers = {"Content-Type": content_type}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.put(url, content=data, headers=headers)
                resp.raise_for_status()

            public_url = f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"
            logger.info("storage.uploaded", key=key, size=len(data))
            return {
                "status": "uploaded",
                "url": public_url,
                "key": key,
                "size_bytes": len(data),
                "content_type": content_type,
            }
        except Exception:
            logger.exception("storage.upload_failed", key=key)
            return {"status": "failed", "key": key}

    async def upload_from_url(self, source_url: str, key: str) -> dict[str, Any]:
        """Download from a URL and upload to S3."""
        if not self.configured:
            return {"status": "skipped", "reason": "S3 not configured", "key": key}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/png")
                return await self.upload(key, resp.content, content_type)
        except Exception:
            logger.exception("storage.upload_from_url_failed", url=source_url)
            return {"status": "failed", "key": key, "source_url": source_url}

    async def download(self, key: str) -> bytes | None:
        """Download a file from S3."""
        if not self.configured:
            return None

        url = f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
        except Exception:
            logger.exception("storage.download_failed", key=key)
            return None

    def get_public_url(self, key: str) -> str:
        """Get the public URL for a stored file."""
        return f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"
