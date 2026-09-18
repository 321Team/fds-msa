"""Verify this migration snapshot. Does not run imported software or contact servers.
Run on the migration PR commit, not as a permanent gate for future implementation edits.
"""
from pathlib import Path
import hashlib, json, sys

root = Path(__file__).resolve().parents[1]
data = json.loads((root / "docs/MIGRATION_MANIFEST.json").read_text(encoding="utf-8"))
errors = []
for item in data["files"]:
    path = root / item["destination_path"]
    if not path.is_file() or path.is_symlink():
        errors.append(item["destination_path"] + ": missing or symlink")
        continue
    value = path.read_bytes()
    digest = hashlib.sha256(value).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    if digest != item["destination_sha256"] or blob != item["destination_blob"]:
        errors.append(item["destination_path"] + ": hash mismatch")
print(json.dumps({"result": "FAIL" if errors else "PASS", "files": len(data["files"]),
                  "errors": errors, "scope": "migration file integrity only"}, ensure_ascii=False))
sys.exit(bool(errors))
