"""Check the supported flat hash-lock profiles; pip resolves full dependencies."""
from pathlib import Path
import re

SERVICES = ("transaction-api", "fds-engine")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9_.+!-]+)")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path, *, locked=False):
    records = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        match = PIN.fullmatch(parts[0])
        if match is None:
            raise ValueError(f"{path}: exact pin required")
        name = normalize(match[1])
        extras = frozenset(normalize(x) for x in (match[2] or "[]")[1:-1].split(",") if x)
        hashes = frozenset(parts[1:])
        if (locked and (not hashes or any(not HASH.fullmatch(x) for x in hashes))) or (not locked and hashes):
            raise ValueError(f"{path}: invalid hash profile")
        if name in records:
            raise ValueError(f"{path}: duplicate package {name}")
        records[name] = (match[3], extras, hashes)
    if not records:
        raise ValueError(f"{path}: empty profile")
    return records


def check(root):
    for service in SERVICES:
        folder = root / service
        roots = read_pins(folder / "requirements.txt")
        test_path = folder / "requirements-test.txt"
        lines = test_path.read_text().splitlines()
        if lines.count("-r requirements.txt") != 1:
            raise ValueError(f"{test_path}: one local runtime include required")
        # Parse test roots without creating or modifying input files.
        test_roots = dict(roots)
        for line in lines:
            if line == "-r requirements.txt" or not line.strip() or line.lstrip().startswith("#"):
                continue
            match = PIN.fullmatch(line)
            if match is None or normalize(match[1]) in test_roots:
                raise ValueError(f"{test_path}: invalid or duplicate test pin")
            extras = frozenset(normalize(x) for x in (match[2] or "[]")[1:-1].split(",") if x)
            test_roots[normalize(match[1])] = (match[3], extras, frozenset())
        runtime = read_pins(folder / "requirements-runtime.lock", locked=True)
        test = read_pins(folder / "requirements-test.lock", locked=True)
        for expected, actual in ((roots, runtime), (test_roots, test)):
            for name, (version, extras, _) in expected.items():
                if name not in actual or actual[name][0] != version or not extras <= actual[name][1]:
                    raise ValueError(f"{service}: root/lock mismatch for {name}")
        for name, (version, extras, hashes) in runtime.items():
            if name not in test or test[name][0] != version or not extras <= test[name][1] or test[name][2] != hashes:
                raise ValueError(f"{service}: runtime/test lock drift for {name}")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
    print("DEPENDENCY_LOCKS=PASS (roots, extras, hashes, runtime/test consistency)")
