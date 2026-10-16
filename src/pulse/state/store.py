"""A thin object store over the R2 (S3 API) bucket that holds pipeline state between runs."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from pulse.runner.stage import RetryableError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

DEFAULT_PREFIX = "state"
_TRANSIENT_CODES = {"SlowDown", "Throttling", "ThrottlingException", "RequestTimeout"}


class PreconditionFailed(Exception):
    """A conditional write lost the race (If-None-Match / If-Match did not hold)."""


@dataclass(frozen=True)
class R2Config:
    bucket: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> R2Config | None:
        """None unless every R2 variable is set: local runs work without R2."""
        values = [
            env.get(k, "").strip()
            for k in ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        ]
        if not all(values):
            return None
        return cls(*values)


def _transient(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return status >= 500 or error.get("Code") in _TRANSIENT_CODES
    return isinstance(exc, BotoCoreError)  # connection resets, timeouts, endpoint errors


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ObjectStore:
    """Keys are relative to ``prefix``. Transient S3 errors become :class:`RetryableError`."""

    def __init__(self, client: S3Client, bucket: str, prefix: str = DEFAULT_PREFIX) -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> ObjectStore | None:
        config = R2Config.from_env(env)
        if config is None:
            return None
        client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
            # R2 does not need the flexible checksums newer botocore sends by default.
            config=Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"mode": "standard", "max_attempts": 3},
            ),
        )
        return cls(client, config.bucket)

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def _call(self, op: str, **kwargs: Any) -> Any:
        try:
            return getattr(self.client, op)(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            if _code(exc) in {"PreconditionFailed", "ConditionalRequestConflict"}:
                raise PreconditionFailed(kwargs.get("Key", "")) from exc
            if _transient(exc):
                raise RetryableError(f"R2 {op} failed: {exc}") from exc
            raise
        except BotoCoreError as exc:
            raise RetryableError(f"R2 {op} failed: {exc}") from exc

    def get(self, key: str) -> tuple[bytes, str] | None:
        """Body and ETag, or None when the key does not exist."""
        try:
            response = self._call("get_object", Key=self._key(key))
        except ClientError as exc:
            if _code(exc) in {"NoSuchKey", "404"}:
                return None
            raise
        return response["Body"].read(), response["ETag"]

    def put(
        self, key: str, body: bytes, *, if_none_match: bool = False, if_match: str | None = None
    ) -> str:
        """Write ``body``; returns the new ETag. Raises PreconditionFailed if a condition fails."""
        kwargs: dict[str, Any] = {"Key": self._key(key), "Body": body}
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        if if_match is not None:
            kwargs["IfMatch"] = if_match
        return str(self._call("put_object", **kwargs)["ETag"])

    def delete(self, key: str) -> None:
        self._call("delete_object", Key=self._key(key))

    def exists(self, key: str) -> bool:
        try:
            self._call("head_object", Key=self._key(key))
        except ClientError as exc:
            if _code(exc) in {"NoSuchKey", "404", "NotFound"}:
                return False
            raise
        return True

    def etags(self, prefix: str) -> dict[str, str]:
        """Key (relative to this store's prefix) -> ETag without quotes, for keys under prefix."""
        out: dict[str, str] = {}
        for page in self._pages(self._key(prefix)):
            for item in page.get("Contents", []):
                key = item["Key"][len(self.prefix) + 1 :] if self.prefix else item["Key"]
                out[key] = item["ETag"].strip('"')
        return out

    def _pages(self, prefix: str) -> Iterator[dict[str, Any]]:
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self._call("list_objects_v2", **kwargs)
            yield page
            if not page.get("IsTruncated"):
                return
            token = page["NextContinuationToken"]

    def upload(self, path: Path, key: str) -> None:
        try:
            self.client.upload_file(str(path), self.bucket, self._key(key))
        except (ClientError, BotoCoreError) as exc:
            if _transient(exc):
                raise RetryableError(f"R2 upload of {key} failed: {exc}") from exc
            raise

    def upload_if_changed(self, path: Path, key: str, remote_etag: str | None) -> bool:
        """Single-part put, skipped when the remote ETag is the file's MD5. True if uploaded."""
        if remote_etag is not None and remote_etag == _md5(path):
            return False
        self.put(key, path.read_bytes())
        return True

    def download(self, key: str, path: Path) -> None:
        """Download beside ``path``, then rename into place: a failure never leaves half a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        try:
            self.client.download_file(self.bucket, self._key(key), str(partial))
        except (ClientError, BotoCoreError) as exc:
            partial.unlink(missing_ok=True)
            if _transient(exc):
                raise RetryableError(f"R2 download of {key} failed: {exc}") from exc
            raise
        partial.replace(path)
