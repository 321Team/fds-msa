"""Generate Python 3.13 linux/amd64 candidate lock files without changing source locks.

This is a pre-merge candidate generator. It preserves every existing pinned package
version except the explicit asyncpg 0.29.0 -> 0.30.0 compatibility delta for
transaction-api, downloads exactly one binary wheel per pinned distribution with
Python 3.13, and records hashes for review. It never writes into the source tree.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\[[A-Za-z0-9_,.-]+\])?=="
    r"(?P<version>[^ ]+)\s+--hash=sha256:(?P<hash>[0-9a-f]{64})$"
)
SERVICES = ("transaction-api", "fds-engine")
LOCKS = ("requirements-runtime.lock", "requirements-test.lock")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def run(argv: list[str], cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, env={
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "PIP_CONFIG_FILE": "/dev/null",
    })


def parse_lock(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        match = LOCK_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{number}: unsupported lock line")
        row = match.groupdict()
        if normalize(row["name"]) == "asyncpg":
            if "transaction-api" not in path.parts:
                raise ValueError(f"{path}:{number}: asyncpg outside transaction-api")
            if row["version"] not in {"0.29.0", "0.30.0"}:
                raise ValueError(f"{path}:{number}: unexpected asyncpg source version")
            row["version"] = "0.30.0"
        rows.append(row)
    if not rows:
        raise ValueError(f"{path}: empty lock")
    return rows


def generate(source: Path, output: Path) -> None:
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError(f"Python 3.13 required, got {sys.version}")
    candidate_sha = os.environ.get("CANDIDATE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
        raise RuntimeError("CANDIDATE_SHA must be an exact commit SHA")

    output.mkdir(parents=True, exist_ok=True)
    wheels_root = output / "wheels"
    locks_root = output / "locks"
    wheels_root.mkdir()
    locks_root.mkdir()

    manifest: dict[str, object] = {
        "schema": "fds.py313-lock-candidate.v1",
        "source_sha": candidate_sha,
        "python": sys.version,
        "platform": "linux/amd64",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "source_lock_versions_preserved": True,
            "target_delta": {"transaction-api:asyncpg": "0.30.0 (0.29.0 source is upgraded; 0.30.0 is stable on rerun)"},
            "binary_only": True,
            "no_deps_per_download": True,
            "delivery_authorization": False,
        },
        "locks": {},
    }

    for service in SERVICES:
        service_manifest: dict[str, object] = {}
        for lock_name in LOCKS:
            source_lock = source / service / lock_name
            rows = parse_lock(source_lock)
            destination_dir = locks_root / service
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination_lock = destination_dir / lock_name
            generated: list[str] = []
            packages: list[dict[str, object]] = []

            for row in rows:
                display_name = row["name"] + (row["extras"] or "")
                spec = f'{display_name}=={row["version"]}'
                package_dir = wheels_root / service / lock_name.removesuffix(".lock") / normalize(row["name"])
                package_dir.mkdir(parents=True, exist_ok=True)
                run([
                    sys.executable, "-I", "-m", "pip", "--isolated",
                    "--disable-pip-version-check", "--no-cache-dir",
                    "download", "--index-url", "https://pypi.org/simple",
                    "--only-binary=:all:", "--no-deps",
                    "--dest", str(package_dir), spec,
                ], source)
                files = sorted(p for p in package_dir.iterdir() if p.is_file())
                if len(files) != 1:
                    raise RuntimeError(f"{spec}: expected exactly one wheel, got {len(files)}")
                wheel = files[0]
                digest = sha256(wheel)
                generated.append(f'{display_name}=={row["version"]} --hash=sha256:{digest}')
                packages.append({
                    "name": row["name"],
                    "extras": row["extras"] or "",
                    "version": row["version"],
                    "wheel": wheel.name,
                    "sha256": digest,
                    "bytes": wheel.stat().st_size,
                })

            destination_lock.write_text("\n".join(generated) + "\n")
            service_manifest[lock_name] = {
                "source_sha256": sha256(source_lock),
                "candidate_sha256": sha256(destination_lock),
                "packages": packages,
            }
        manifest["locks"][service] = service_manifest

    manifest_path = output / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    files = sorted(
        p for p in output.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(p)}  {p.relative_to(output)}\n" for p in files)
    )
    print(json.dumps({
        "result": "PASS",
        "source_sha": candidate_sha,
        "locks": {
            service: list(manifest["locks"][service].keys())
            for service in SERVICES
        },
    }, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_py313_lock_candidate.py SOURCE OUTPUT")
    generate(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
