"""Local-only #354 benchmark: uv run python tests/state/benchmark_restore.py.

Uses in-process moto, synthetic bytes and temporary directories; never reads R2
credentials. An optional --latency-ms adds a labeled per-request delay model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
import moto
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from moto import mock_aws

from pulse.contracts.enums import RunType, StageStatus
from pulse.runner.stage import StageContext, SystemClock
from pulse.state import StateSync
from pulse.state.store import ObjectStore
from pulse.warehouse import WAREHOUSE_FILE


class Clock(SystemClock):
    def now(self) -> datetime:
        return datetime(2026, 10, 26, 11, tzinfo=UTC)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-ms", type=float, default=0)
    args = parser.parse_args()
    with mock_aws(), tempfile.TemporaryDirectory(prefix="pulse-354-") as directory:
        root = Path(directory)
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="synthetic",
            aws_secret_access_key="synthetic",
            config=Config(max_pool_connections=16),
        )
        client.create_bucket(Bucket="pulse-benchmark")
        store = ObjectStore(client, "pulse-benchmark")
        source = root / "seed.duckdb"
        with source.open("wb") as handle:
            block = bytes(range(256)) * (64 * 1024)
            for _ in range(64):
                handle.write(block)  # exactly 1 GiB, no giant in-memory buffer
        expected = {WAREHOUSE_FILE: digest(source)}
        store.upload(source, WAREHOUSE_FILE)
        source.unlink()
        for prefix, count, size in (("sources", 910, 64 * 1024), ("narratives", 280, 4 * 1024)):
            for i in range(count):
                key = f"{prefix}/{i:04d}.synthetic"
                body = (f"synthetic-{i:04d}\n".encode() * size)[:size]
                store.put(key, body)
                expected[key] = hashlib.sha256(body).hexdigest()
        if args.latency_ms:

            def delay(**_: object) -> None:
                time.sleep(args.latency_ms / 1000)

            client.meta.events.register("before-call.s3", delay)

        # Previous code: serial source/narrative files, warehouse using SDK defaults.
        started = time.perf_counter()
        for prefix in ("sources/", "narratives/"):
            for key in sorted(store.etags(prefix)):
                target = root / "sequential" / key
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + ".partial")
                client.download_file(store.bucket, store._key(key), str(partial))
                partial.replace(target)
        client.download_file(
            store.bucket,
            store._key(WAREHOUSE_FILE),
            str(root / "sequential" / WAREHOUSE_FILE),
            Config=TransferConfig(),
        )
        sequential = time.perf_counter() - started
        sync = StateSync(lambda: store, new_token=lambda: "synthetic-benchmark")
        ctx = StageContext(
            "weekly-2026-W43-1", RunType.WEEKLY, "2026-W43", root / "parallel", Clock()
        )
        started = time.perf_counter()
        result = sync.restore(ctx)
        parallel = time.perf_counter() - started
        assert result.status is StageStatus.SUCCESS, result
        for mode in ("sequential", "parallel"):
            assert {
                p.relative_to(root / mode).as_posix()
                for p in (root / mode).rglob("*")
                if p.is_file()
            } == set(expected)
            for key, sha256 in expected.items():
                assert digest(root / mode / key) == sha256, (mode, key)
        sync.release(ctx)
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "processor": platform.processor(),
                    "python": platform.python_version(),
                    "boto3": boto3.__version__,
                    "moto": moto.__version__,
                    "sources": 910,
                    "source_bytes_each": 65536,
                    "narratives": 280,
                    "narrative_bytes_each": 4096,
                    "warehouse_bytes": 1 << 30,
                    "modeled_request_latency_ms": args.latency_ms,
                    "sequential_seconds": round(sequential, 3),
                    "parallel_seconds": round(parallel, 3),
                    "speedup": round(sequential / parallel, 2),
                    "sha256_verified_files": len(expected),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
