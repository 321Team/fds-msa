"""Ephemeral GitHub-hosted candidate Build/Scan; never a delivery authorization."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

BASE = "docker.io/library/python@sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b"
BASE_CONFIG = "sha256:9e87977b867847e186d066f531ef783b006d582a985c341c269446088d90f2c4"
BINARY_SHA = "d89bcc6510a267f11b773398cbf1be5520ce39f9e8b6633178c4487f05b7d791"
ARCHIVE_SHA = "2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"
SERVICES = ("transaction-api", "fds-engine")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verified_hash(path):
    require(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    expected = digest(path)
    system = subprocess.check_output(["sha256sum", str(path)], text=True, timeout=120).split()[0]
    require(system == expected, "INDEPENDENT_HASH_MISMATCH")
    return expected


def metadata_valid(data, checked):
    require(type(data.get("Version")) is int and data["Version"] == 2, "DB_SCHEMA")
    times = []
    for key in ("UpdatedAt", "DownloadedAt", "NextUpdate"):
        parsed = datetime.fromisoformat(data[key].replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "DB_TIMEZONE")
        times.append(parsed)
    updated, downloaded, next_update = times
    require(updated <= downloaded <= checked < next_update and updated < next_update, "DB_FRESHNESS")


def report_decision(report, rc, image):
    require(rc in (0, 10), "SCANNER_ERROR")
    require(report.get("SchemaVersion") == 2, "REPORT_SCHEMA")
    require(report.get("Trivy", {}).get("Version") == "0.74.0", "REPORT_TRIVY_VERSION")
    require(report.get("ArtifactType") == "container_image", "REPORT_ARTIFACT_TYPE")
    meta = report.get("Metadata", {})
    require(meta.get("ImageID") == image["Id"], "REPORT_IMAGE_ID")
    require(meta.get("DiffIDs") == image["RootFS"]["Layers"], "REPORT_LAYERS")
    results = report.get("Results")
    require(isinstance(results, list) and any(r.get("Class") == "os-pkgs" and r.get("Packages") for r in results), "OS_INVENTORY_MISSING")
    packages = {p.get("Name", "").lower().replace("_", "-"): p.get("Version") for r in results if r.get("Type") == "python-pkg" for p in r.get("Packages", [])}
    require(packages.get("fastapi") == "0.141.1" and packages.get("starlette") == "1.7.0", "APP_INVENTORY_MISSING_OR_STALE")
    findings = [v for r in results for v in r.get("Vulnerabilities", [])]
    require(all(v.get("Severity") in ("HIGH", "CRITICAL") for v in findings), "REPORT_SEVERITY")
    require((rc == 10) == bool(findings), "EXIT_COUNT_MISMATCH")
    return {"status": "BLOCK" if findings else "PASS", "counts": {s: sum(v["Severity"] == s for v in findings) for s in ("HIGH", "CRITICAL")}, "unique_cves": len({v["VulnerabilityID"] for v in findings})}


def execute(source, output):
    os.umask(0o077)
    require(os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted", "GITHUB_HOSTED_ONLY")
    require(os.environ.get("GITHUB_REPOSITORY") == "321Team/fds-msa", "REPOSITORY")
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request", "PR_EVENT_ONLY")
    expected = os.environ.get("CANDIDATE_SHA", "")
    require(re.fullmatch("[0-9a-f]{40}", expected), "SOURCE_SHA")
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() == expected, "SOURCE_HEAD_MISMATCH")
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True).strip(), "SOURCE_DIRTY")
    output.mkdir(mode=0o700)
    work = output.parent / (output.name + "-work")
    work.mkdir(mode=0o700)
    clean_env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")}
    clean_env.update(LC_ALL="C", PIP_CONFIG_FILE="/dev/null")
    result = {"scope": "GITHUB_HOSTED_CANDIDATE_ONLY", "source_sha": expected, "workflow_sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "started_at": now().isoformat(), "decision": "ERROR", "DELIVERY_GATE": "NOT_VERIFIED", "PUSH": "NOT_EXECUTED", "DEPLOY": "NOT_EXECUTED", "images": {s: {"build": "NOT_BUILT", "scan": "NOT_SCANNED"} for s in SERVICES}, "commands": []}

    def write(name, data):
        (output / name).write_text(json.dumps(data, indent=2) + "\n")

    def run(label, argv, timeout=600, allowed=(0,)):
        write(label + "-argv.json", argv)
        with (output / (label + ".log")).open("wb") as log:
            proc = subprocess.run(argv, cwd=source, env=clean_env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        result["commands"].append({"label": label, "rc": proc.returncode})
        require(proc.returncode in allowed, label + "_FAILED_RC_" + str(proc.returncode))
        return proc.returncode

    db_hashes = {}
    def db_check():
        for name, expected_hash in db_hashes.items():
            require(verified_hash(output / name) == expected_hash, "DB_CHANGED_" + name)
        metadata_valid(json.loads((output / "cache/db/metadata.json").read_text()), now())

    rc = 1
    try:
        run("docker-version", ["docker", "version"])
        run("buildx-version", ["docker", "buildx", "version"])
        run("base-pull", ["docker", "pull", "--platform", "linux/amd64", BASE])
        run("base-inspect", ["docker", "image", "inspect", BASE])
        base = json.loads((output / "base-inspect.log").read_text())[0]
        require(base["Id"] == BASE_CONFIG and base["Architecture"] == "amd64" and base["Os"] == "linux", "BASE_IDENTITY")
        result["base"] = {"reference": BASE, "config": BASE_CONFIG, "diff_ids": base["RootFS"]["Layers"]}
        for service in SERVICES:
            result["images"][service]["build"] = "BUILDING"
            require((source / service / "Dockerfile").read_text().splitlines()[0] == "FROM " + BASE, "DOCKERFILE_BASE")
            wheels = work / (service + "-wheels")
            wheels.mkdir()
            run(service + "-download", ["python3", "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir", "download", "--index-url", "https://pypi.org/simple", "--only-binary=:all:", "--require-hashes", "-r", str(source / service / "requirements-runtime.lock"), "--dest", str(wheels)])
            write(service + "-wheels.json", {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(wheels.iterdir())})
            tag = "fds-candidate/" + service + ":" + expected
            run(service + "-build", ["docker", "buildx", "build", "--platform", "linux/amd64", "--network", "none", "--pull=false", "--no-cache", "--load", "--build-context", "python-wheels=" + str(wheels), "--tag", tag, str(source / service)])
            run(service + "-inspect", ["docker", "image", "inspect", tag])
            identity = json.loads((output / (service + "-inspect.log")).read_text())[0]
            require(identity["Architecture"] == "amd64" and identity["Os"] == "linux", "IMAGE_PLATFORM")
            require(identity["Config"]["User"] == "fdsuser", "IMAGE_USER")
            require(identity["RootFS"]["Layers"][:len(base["RootFS"]["Layers"])] == base["RootFS"]["Layers"], "BASE_LAYERS")
            archive = output / (service + ".docker.tar")
            run(service + "-save", ["docker", "save", "--output", str(archive), tag])
            result["images"][service].update(build="PASS", image=identity, archive_sha256=verified_hash(archive))
        release = work / "trivy.tar.gz"
        run("trivy-download", ["curl", "-q", "--fail", "--location", "--proto", "=https", "--tlsv1.2", "--output", str(release), "https://github.com/aquasecurity/trivy/releases/download/v0.74.0/trivy_0.74.0_Linux-64bit.tar.gz"])
        require(verified_hash(release) == ARCHIVE_SHA, "TRIVY_ARCHIVE_HASH")
        binary = work / "trivy"
        with tarfile.open(release) as package:
            member = package.getmember("trivy")
            require(member.isfile(), "TRIVY_FILE")
            with package.extractfile(member) as src, binary.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        require(verified_hash(binary) == BINARY_SHA, "TRIVY_BINARY_HASH")
        binary.chmod(0o755)
        result["binary_sha256"] = BINARY_SHA
        cache = output / "cache"
        cache.mkdir()
        empty_config, empty_ignore = output / "empty.yaml", output / "empty.ignore"
        empty_config.write_text("{}\n")
        empty_ignore.write_text("")
        run("db-download", [str(binary), "image", "--cache-dir", str(cache), "--config", str(empty_config), "--db-repository", "ghcr.io/aquasecurity/trivy-db:2", "--download-db-only", "--skip-version-check", "--no-progress", "--timeout", "5m"], timeout=330)
        for name in ("cache/db/trivy.db", "cache/db/metadata.json"):
            db_hashes[name] = verified_hash(output / name)
        result["db_before"] = db_hashes.copy()
        result["db_metadata"] = json.loads((cache / "db/metadata.json").read_text())
        db_check()
        (output / "DB_SHA256SUMS").write_text("".join(h + "  " + name + "\n" for name, h in db_hashes.items()))
        for service in SERVICES:
            db_check()
            result["images"][service]["scan"] = "SCANNING"
            archive = output / (service + ".docker.tar")
            report_path = output / (service + "-report.json")
            scan_rc = run(service + "-scan", [str(binary), "image", "--input", str(archive), "--cache-dir", str(cache), "--config", str(empty_config), "--ignorefile", str(empty_ignore), "--ignore-unfixed=false", "--scanners", "vuln", "--pkg-types", "os,library", "--list-all-pkgs", "--skip-db-update", "--skip-java-db-update", "--offline-scan", "--skip-version-check", "--severity", "HIGH,CRITICAL", "--exit-code", "10", "--format", "json", "--output", str(report_path), "--no-progress", "--timeout", "10m"], timeout=630, allowed=(0, 10))
            db_check()
            require(verified_hash(binary) == BINARY_SHA, "BINARY_CHANGED")
            require(verified_hash(archive) == result["images"][service]["archive_sha256"], "ARCHIVE_CHANGED")
            decision = report_decision(json.loads(report_path.read_text()), scan_rc, result["images"][service]["image"])
            result["images"][service].update(scan=decision["status"], scan_exit_code=scan_rc, findings=decision, report_sha256=verified_hash(report_path))
            if decision["status"] == "BLOCK":
                result["decision"] = "BLOCK"
                rc = 10
                break
        else:
            result["decision"] = "PASS_CANDIDATE_ONLY"
            rc = 0
    except Exception as error:
        result.update(decision="ERROR", error_type=type(error).__name__, error=str(error))
        for image in result["images"].values():
            if image["build"] == "BUILDING":
                image["build"] = "ERROR"
            if image["scan"] == "SCANNING":
                image["scan"] = "ERROR"
        rc = 1
    finally:
        if db_hashes:
            try:
                db_check()
                result["db_integrity"] = "PASS"
            except Exception as error:
                result.update(decision="ERROR", db_integrity="FAIL", db_error=str(error))
                rc = 1
        result["finished_at"] = now().isoformat()
        write("result.json", result)
        files = sorted(p for p in output.rglob("*") if p.is_file())
        (output / "SHA256SUMS").write_text("".join(digest(p) + "  " + str(p.relative_to(output)) + "\n" for p in files))
        print(json.dumps(result), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(execute(Path(__file__).resolve().parents[1], Path(sys.argv[1]).resolve()))
