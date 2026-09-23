"""Verify this migration snapshot. Does not run imported software or contact servers.
Run on the migration PR commit, not as a permanent gate for future implementation edits.
Usage: python tools/verify_migration.py [--rev <commit>]  (--rev reads files from that Git commit)
Post-migration edits recorded in docs/MIGRATION_CHANGES.json pass only when the file matches the recorded hashes.
"""
from pathlib import Path
import hashlib, json, subprocess, sys

root = Path(__file__).resolve().parents[1]
args = sys.argv[1:]
if args and (len(args) != 2 or args[0] != "--rev"):
    sys.exit("usage: python tools/verify_migration.py [--rev <commit>]")
rev = args[1] if args else None

def git(*cmd):
    done = subprocess.run(["git", "-C", str(root), *cmd], capture_output=True)
    if done.returncode:
        sys.exit("git " + " ".join(cmd) + ": " + done.stderr.decode(errors="replace").strip())
    return done.stdout

if rev:
    rev = git("rev-parse", "--verify", rev + "^{commit}").decode().strip()
    tree = {}
    for line in git("ls-tree", "-r", "-z", rev).split(b"\0"):
        if line:
            meta, name = line.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            tree[name.decode("utf-8")] = (mode, kind)
    data = json.loads(git("show", rev + ":docs/MIGRATION_MANIFEST.json").decode("utf-8"))
    ledger = git("show", rev + ":docs/MIGRATION_CHANGES.json") if "docs/MIGRATION_CHANGES.json" in tree else None
else:
    data = json.loads((root / "docs/MIGRATION_MANIFEST.json").read_text(encoding="utf-8"))
    ledger_path = root / "docs/MIGRATION_CHANGES.json"
    ledger = ledger_path.read_bytes() if ledger_path.is_file() else None
changes = {}
for change in json.loads(ledger.decode("utf-8"))["changes"] if ledger else []:
    if change["path"] in changes:
        sys.exit("duplicate path in docs/MIGRATION_CHANGES.json: " + change["path"])
    changes[change["path"]] = change
errors, approved = [], []
unknown = sorted(set(changes) - {item["destination_path"] for item in data["files"]})
errors += [name + ": change record for a path not in manifest" for name in unknown]
for item in data["files"]:
    name = item["destination_path"]
    if rev:
        if tree.get(name, ("", ""))[1] != "blob" or tree[name][0] == "120000":
            errors.append(name + ": missing or symlink")
            continue
        if tree[name][0] != item["git_mode"]:
            errors.append(name + ": mode mismatch")
        value = git("cat-file", "blob", rev + ":" + name)
    else:
        path = root / name
        if not path.is_file() or path.is_symlink():
            errors.append(name + ": missing or symlink")
            continue
        value = path.read_bytes()
    digest = hashlib.sha256(value).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    change = changes.get(name)
    if change and digest == change["current_sha256"] and blob == change["current_blob"]:
        approved.append(name + ": " + change["change_commit"][:7])
    elif digest != item["destination_sha256"] or blob != item["destination_blob"]:
        errors.append(name + (": hash differs from change record" if change else ": hash mismatch"))
print(json.dumps({"result": "FAIL" if errors else "PASS", "files": len(data["files"]),
                  "errors": errors, "approved_changes": approved, "source": rev or "working tree",
                  "scope": "migration file integrity only"}, ensure_ascii=False))
sys.exit(bool(errors))
