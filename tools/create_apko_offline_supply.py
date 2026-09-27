#!/usr/bin/env python3
"""Create a hash-bound Wolfi/apko offline supply bundle for P1 on-prem delivery.

Inputs are already-built apko builder/runtime OCI archives plus wheelhouses produced
from this exact source commit. This tool does not build application images, scan,
push, deploy, or authorize delivery. It only packages immutable supply bytes and
writes a manifest that a separate infra-cicd consumer can verify.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import zipfile

SERVICES = ("transaction-api", "fds-engine")
MODES = ("runtime", "test")
LOCK_NAME = {"runtime": "requirements-runtime.lock", "test": "requirements-test.lock"}
HEX = re.compile(r"[0-9a-f]{64}")
LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\\[[A-Za-z0-9_,.-]+\\])?=="
    r"(?P<version>[^ ]+)\\s+--hash=sha256:(?P<hash>[0-9a-f]{64})$"
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def copy_regular(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"regular file required: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)


def oci_identity(path: Path) -> dict[str, object]:
    """Verify an OCI archive's index -> manifest -> config bindings."""
    members: dict[str, bytes] = {}
    with tarfile.open(path, "r:") as archive:
        seen = set()
        for member in archive:
            name = member.name.removeprefix("./")
            if name in seen:
                raise RuntimeError(f"duplicate OCI member: {name}")
            seen.add(name)
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise RuntimeError(f"unsupported OCI member: {name}")
            if name in {"index.json", "oci-layout"} or name.startswith("blobs/sha256/"):
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"cannot read OCI member: {name}")
                members[name] = extracted.read()

    if "index.json" not in members or "oci-layout" not in members:
        raise RuntimeError("OCI index/layout missing")
    layout = json.loads(members["oci-layout"])
    if layout != {"imageLayoutVersion": "1.0.0"}:
        raise RuntimeError(f"unsupported OCI layout: {layout}")
    index_raw = members["index.json"]
    index = json.loads(index_raw)
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or len(manifests) != 1:
        raise RuntimeError("exactly one OCI manifest required")
    desc = manifests[0]
    digest = desc.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError("invalid OCI manifest digest")
    manifest_key = "blobs/sha256/" + digest.split(":", 1)[1]
    manifest_raw = members.get(manifest_key)
    if manifest_raw is None or "sha256:" + sha256_bytes(manifest_raw) != digest:
        raise RuntimeError("OCI manifest digest mismatch")
    manifest = json.loads(manifest_raw)
    config_desc = manifest.get("config", {})
    config_digest = config_desc.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest):
        raise RuntimeError("invalid OCI config digest")
    config_key = "blobs/sha256/" + config_digest.split(":", 1)[1]
    config_raw = members.get(config_key)
    if config_raw is None or "sha256:" + sha256_bytes(config_raw) != config_digest:
        raise RuntimeError("OCI config digest mismatch")
    config = json.loads(config_raw)
    if config.get("architecture") != "amd64" or config.get("os") != "linux":
        raise RuntimeError("OCI platform must be linux/amd64")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise RuntimeError("OCI layers missing")
    for layer in layers:
        ldigest = layer.get("digest", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", ldigest):
            raise RuntimeError("invalid OCI layer digest")
        key = "blobs/sha256/" + ldigest.split(":", 1)[1]
        raw = members.get(key)
        if raw is None or "sha256:" + sha256_bytes(raw) != ldigest:
            raise RuntimeError("OCI layer digest mismatch")
    diff_ids = config.get("rootfs", {}).get("diff_ids")
    if not isinstance(diff_ids, list) or len(diff_ids) != len(layers):
        raise RuntimeError("OCI diff_ids/layers mismatch")
    return {
        "archive_sha256": sha256(path),
        "index_digest": "sha256:" + sha256_bytes(index_raw),
        "manifest_digest": digest,
        "config_digest": config_digest,
        "diff_ids": diff_ids,
        "layer_count": len(layers),
        "platform": "linux/amd64",
    }


def parse_roots(source: Path, service: str, mode: str) -> list[str]:
    runtime = (source / service / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if mode == "runtime":
        rows = runtime
    else:
        test = (source / service / "requirements-test.txt").read_text(encoding="utf-8").splitlines()
        if test.count("-r requirements.txt") != 1:
            raise RuntimeError(f"{service}: test requirements must include one -r requirements.txt")
        rows = runtime + [row for row in test if row and row != "-r requirements.txt"]
    clean = [row.strip() for row in rows if row.strip()]
    if not clean or any("://" in row or "@" in row for row in clean):
        raise RuntimeError(f"{service}/{mode}: unsupported root requirement")
    return clean


def parse_lock(path: Path) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        match = LOCK_LINE.fullmatch(line)
        if not match:
            raise RuntimeError(f"{path}:{number}: unsupported lock line")
        data = match.groupdict()
        key = normalize(data["name"])
        if key in seen:
            raise RuntimeError(f"{path}:{number}: duplicate package")
        seen.add(key)
        rows.append({
            "name": key,
            "display_name": data["name"],
            "extras": data["extras"] or "",
            "version": data["version"],
            "sha256": data["hash"],
        })
    if not rows:
        raise RuntimeError(f"{path}: empty lock")
    return rows


def wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        metadata = [entry for entry in entries if re.fullmatch(r"[^/]+\\.dist-info/METADATA", entry.filename)]
        if len(metadata) != 1:
            raise RuntimeError(f"{path}: one METADATA required")
        msg = BytesParser().parsebytes(archive.read(metadata[0]))
    if len(msg.get_all("Name", [])) != 1 or len(msg.get_all("Version", [])) != 1:
        raise RuntimeError(f"{path}: wheel identity missing")
    return normalize(msg["Name"]), msg["Version"]


def build_profile(source: Path, work: Path, output: Path, service: str, mode: str) -> dict[str, str]:
    lock_path = source / service / LOCK_NAME[mode]
    lock_rows = parse_lock(lock_path)
    wheel_dir = work / "wheels" / f"{service}-{mode}"
    if not wheel_dir.is_dir() or wheel_dir.is_symlink():
        raise RuntimeError(f"wheelhouse missing: {wheel_dir}")
    wheels = [p for p in wheel_dir.iterdir() if p.is_file() and not p.is_symlink()]
    by_identity: dict[tuple[str, str], Path] = {}
    for wheel in wheels:
        identity = wheel_metadata(wheel)
        if identity in by_identity:
            raise RuntimeError(f"duplicate wheel identity: {identity}")
        by_identity[identity] = wheel

    profile = output / "profiles" / f"{service}-{mode}"
    (profile / "wheels").mkdir(parents=True)
    inventory = []
    for row in lock_rows:
        key = (row["name"], row["version"])
        wheel = by_identity.get(key)
        if wheel is None:
            raise RuntimeError(f"{service}/{mode}: missing wheel {key}")
        actual = sha256(wheel)
        if actual != row["sha256"]:
            raise RuntimeError(f"{service}/{mode}: wheel hash mismatch for {key}")
        destination = profile / "wheels" / wheel.name
        copy_regular(wheel, destination)
        inventory.append({
            "name": row["name"],
            "version": row["version"],
            "file": wheel.name,
            "sha256": actual,
        })
    if len(inventory) != len(wheels):
        extras = sorted(set(p.name for p in wheels) - set(row["file"] for row in inventory))
        raise RuntimeError(f"{service}/{mode}: extra wheels: {extras}")

    roots = parse_roots(source, service, mode)
    roots_path = profile / "roots.txt"
    roots_path.write_text("\n".join(roots) + "\n", encoding="utf-8")
    lock_copy = profile / "requirements.lock"
    copy_regular(lock_path, lock_copy)
    inventory_path = profile / "inventory.json"
    inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "roots_sha256": sha256(roots_path),
        "lock_sha256": sha256(lock_copy),
        "inventory_sha256": sha256(inventory_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("source_sha")
    args = parser.parse_args()
    source = args.source.resolve()
    work = args.work.resolve()
    output = args.output.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise RuntimeError("exact source SHA required")
    if output.exists():
        raise RuntimeError("output directory must not exist")
    output.mkdir(parents=True)

    images = {}
    for label in ("builder", "runtime"):
        src = work / f"{label}.oci.tar"
        dest = output / f"{label}.oci.tar"
        copy_regular(src, dest)
        images[label] = oci_identity(dest)

    profiles = {}
    for service in SERVICES:
        for mode in MODES:
            profiles[f"{service}-{mode}"] = build_profile(source, work, output, service, mode)

    requirements = {}
    for service in SERVICES:
        for filename in ("requirements.txt", "requirements-test.txt", "requirements-runtime.lock", "requirements-test.lock"):
            requirements[f"{service}/{filename}"] = sha256(source / service / filename)

    inputs_dir = output / "inputs"
    inputs_dir.mkdir()
    input_hashes = {}
    for filename in (
        "wolfi-python313-builder.apko.yaml",
        "wolfi-python313-builder.apko.lock.json",
        "wolfi-python313-runtime.apko.yaml",
        "wolfi-python313-runtime.apko.lock.json",
    ):
        src = source / "ci" / "apko" / filename
        dest = inputs_dir / filename
        copy_regular(src, dest)
        input_hashes[filename] = sha256(dest)

    manifest = {
        "schema": "fds.apko-offline-supply.v1",
        "source": {"repository": "321Team/fds-msa", "commit": args.source_sha},
        "platform": "linux/amd64",
        "apko": {
            "version": os.environ.get("APKO_VERSION", ""),
            "release_archive_sha256": os.environ.get("APKO_ARCHIVE_SHA", ""),
        },
        "images": images,
        "profiles": profiles,
        "requirements": requirements,
        "apko_inputs": input_hashes,
        "policy": {
            "delivery_authorization": False,
            "harbor_push": "NOT_EXECUTED",
            "kubernetes_deploy": "NOT_EXECUTED",
            "high_critical_exception": False,
            "purpose": "ON_PREM_TEST_BUILD_SCAN_SUPPLY_ONLY",
        },
    }
    if manifest["apko"]["version"] != "1.4.4" or not HEX.fullmatch(manifest["apko"]["release_archive_sha256"]):
        raise RuntimeError("approved apko version/archive hash environment required")

    manifest_path = output / "SUPPLY_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output)}\n" for path in files),
        encoding="utf-8",
    )
    print(json.dumps({
        "result": "PASS",
        "source_sha": args.source_sha,
        "builder_archive_sha256": images["builder"]["archive_sha256"],
        "runtime_archive_sha256": images["runtime"]["archive_sha256"],
        "profiles": sorted(profiles),
        "delivery_authorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
