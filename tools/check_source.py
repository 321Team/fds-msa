"""Static checks only; no deployment, imported script execution, or network."""
import ast, json, re, subprocess, sys
from pathlib import Path
import yaml
root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
errors = []
count = 0
for name in paths:
    if not name: continue
    p = root / name
    try:
        if p.is_symlink(): raise ValueError("symlinks require explicit review")
        data = p.read_bytes()
        text = data.decode("utf-8")
        if re.search(r"^-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----", text, re.M):
            raise ValueError("private-key material")
        if re.search(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})", text):
            raise ValueError("credential pattern")
        if p.suffix == ".py": ast.parse(text)
        if p.suffix in (".yaml", ".yml"): list(yaml.safe_load_all(text))
        if p.suffix == ".json": json.loads(text)
        count += 1
    except Exception as error:
        errors.append({"path": name, "error": str(error)})
print(json.dumps({"files": count, "errors": errors, "result": "FAIL" if errors else "PASS"}))
sys.exit(bool(errors))
