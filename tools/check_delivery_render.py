"""Check a rendered ROSA delivery file against deploy/delivery/rosa.yaml.

Producer (#43) and consumer (#46) run the same check on the same bytes:
`kubectl kustomize deploy/overlays/rosa-app > app.yaml` then
`python3 tools/check_delivery_render.py --mode app app.yaml`.
No cluster access. Exit 0 = PASS, 1 = FAIL (reasons in JSON), 2 = usage/parse error.
The JSON lists object identities, images and the input SHA-256 so the consumer can bind
the file it applies to this result. Secret values are never read (only referenced names).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "deploy" / "delivery" / "rosa.yaml"
CLUSTER_SCOPED = {"Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition",
                  "PersistentVolume", "StorageClass", "SecurityContextConstraints",
                  "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}
DIGEST_REF = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
DNS_HOST = re.compile(rf"{DNS_LABEL}(?:\.{DNS_LABEL})*")
PENDING = "PENDING"


def dns_host(value):
    return isinstance(value, str) and len(value) <= 253 and DNS_HOST.fullmatch(value) is not None


def ident(doc):
    return (doc.get("apiVersion"), doc.get("kind"), (doc.get("metadata") or {}).get("name"))


def pod_spec(doc):
    return ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}


def secret_names(spec):
    names = set()
    # 이미지 pull Secret도 같은 namespace Secret 참조이므로 승인 목록에 묶는다.
    for ref in spec.get("imagePullSecrets", []) or []:
        if ref.get("name"):
            names.add(ref["name"])
    for c in spec.get("containers", []) + spec.get("initContainers", []):
        for env in c.get("env", []) or []:
            ref = ((env.get("valueFrom") or {}).get("secretKeyRef") or {}).get("name")
            if ref:
                names.add(ref)
        for src in c.get("envFrom", []) or []:
            ref = (src.get("secretRef") or {}).get("name")
            if ref:
                names.add(ref)
    for vol in spec.get("volumes", []) or []:
        ref = (vol.get("secret") or {}).get("secretName")
        if ref:
            names.add(ref)
        for proj in ((vol.get("projected") or {}).get("sources") or []):
            ref = (proj.get("secret") or {}).get("name")
            if ref:
                names.add(ref)
    return names


def check(text, mode, contract, allow_placeholders=False):
    errors = []
    try:
        docs = [d for d in yaml.safe_load_all(text) if d]
    except yaml.YAMLError as exc:
        return {"result": "FAIL", "errors": [f"yaml: {exc}"], "objects": []}
    section = contract[mode]
    expected = {(o["apiVersion"], o["kind"], o["name"]) for o in section["objects"]}
    ns = contract["namespace"]
    seen = []
    for d in docs:
        if not isinstance(d, dict) or "kind" not in d:
            errors.append("non-object document")
            continue
        i = ident(d)
        seen.append(i)
        kind, name = i[1], i[2]
        if kind in CLUSTER_SCOPED:
            errors.append(f"cluster-scoped kind not allowed: {kind}/{name}")
        if (d.get("metadata") or {}).get("namespace") != ns:
            errors.append(f"{kind}/{name}: namespace must be {ns}")
    dup = {i for i in seen if seen.count(i) > 1}
    if dup:
        errors.append(f"duplicate objects: {sorted(map(list, dup))}")
    if set(seen) - expected:
        errors.append(f"not in {mode} allowlist: {sorted(map(list, set(seen) - expected))}")
    if expected - set(seen):
        errors.append(f"missing from render: {sorted(map(list, expected - set(seen)))}")

    images, hosts = [], set()
    for d in docs:
        if not isinstance(d, dict):
            continue
        kind, name = d.get("kind"), (d.get("metadata") or {}).get("name")
        if kind == "ServiceAccount" and d.get("automountServiceAccountToken") is not False:
            errors.append(f"ServiceAccount/{name}: automountServiceAccountToken must be false")
        if kind == "Deployment":
            spec = pod_spec(d)
            want_sa = section.get("service_accounts", {}).get(name)
            if spec.get("serviceAccountName") != want_sa:
                errors.append(f"Deployment/{name}: serviceAccountName must be {want_sa}")
            if spec.get("automountServiceAccountToken") is not False:
                errors.append(f"Deployment/{name}: automountServiceAccountToken must be false")
            refs = secret_names(spec)
            allowed = set(section.get("secret_refs", {}).get(name, []))
            if refs - allowed:
                errors.append(f"Deployment/{name}: unapproved Secret refs {sorted(refs - allowed)}")
            if spec.get("hostNetwork") or spec.get("hostPID") or spec.get("hostIPC"):
                errors.append(f"Deployment/{name}: host namespaces not allowed")
            for vol in spec.get("volumes", []) or []:
                if "hostPath" in vol:
                    errors.append(f"Deployment/{name}: hostPath volume not allowed")
            if "runAsUser" in (spec.get("securityContext") or {}):
                errors.append(f"Deployment/{name}: fixed runAsUser not allowed (SCC assigns UID)")
            for c in spec.get("containers", []) + spec.get("initContainers", []):
                sc = c.get("securityContext") or {}
                if sc.get("privileged") or sc.get("allowPrivilegeEscalation") is not False:
                    errors.append(f"Deployment/{name}/{c.get('name')}: privileged or escalation allowed")
                if "runAsUser" in sc:
                    errors.append(f"Deployment/{name}/{c.get('name')}: fixed runAsUser not allowed")
                image = c.get("image", "")
                images.append({"deployment": name, "container": c.get("name"), "image": image})
                if not isinstance(image, str) or not DIGEST_REF.fullmatch(image):
                    errors.append(f"Deployment/{name}/{c.get('name')}: image must be pinned by digest")
            labels = ((d.get("spec") or {}).get("template") or {}).get("metadata", {}).get("labels", {})
            want_label = section.get("onprem_egress_label", {}).get(name)
            if labels.get("onprem-egress") != want_label:
                errors.append(f"Deployment/{name}: onprem-egress label must be {want_label!r}")
        if kind == "Route":
            host = (d.get("spec") or {}).get("host")
            if dns_host(host):
                hosts.add(host)
            else:
                errors.append(f"Route/{name}: nonempty DNS host required, got {host!r}")
    approved_host = (section.get("route_host") or {}).get("approved")
    if mode == "app":
        if len(hosts) != 1:
            errors.append(f"Routes must share one host: {sorted(hosts)}")
        if approved_host in (None, "", PENDING):
            # 승인 host가 계약에 기록되기 전에는 전달 회차를 시작하지 않는다(infra-rosa#5 v3.2 조건 2).
            if not allow_placeholders:
                errors.append("approved Route host not recorded in contract (PENDING): stop before first write")
        elif not dns_host(approved_host):
            errors.append(f"contract route_host.approved is not a DNS host: {approved_host!r}")
        elif hosts and hosts != {approved_host}:
            errors.append(f"Route host must equal approved host {approved_host}: {sorted(hosts)}")

    placeholders = [m for m in contract.get("placeholder_markers", []) if m in text]
    if placeholders and not allow_placeholders:
        errors.append(f"placeholder values remain: {placeholders}")
    return {
        "schema": "fds.rosa-delivery-render-check.v1",
        "mode": mode,
        "namespace": ns,
        "objects": sorted(" ".join(map(str, i)) for i in seen),
        "images": images,
        "route_hosts": sorted(hosts),
        "approved_route_host": approved_host if mode == "app" else None,
        "placeholders": placeholders,
        "placeholders_allowed": allow_placeholders,
        "result": "FAIL" if errors else "PASS",
        "errors": errors,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mode", choices=("app", "prereq"), required=True)
    p.add_argument("--contract", type=Path, default=CONTRACT)
    p.add_argument("--allow-placeholders", action="store_true",
                   help="CI render check only; a delivery run must not use this flag")
    p.add_argument("rendered", type=Path)
    a = p.parse_args(argv)
    try:
        data = a.rendered.read_bytes()
        contract = yaml.safe_load(a.contract.read_text(encoding="utf-8"))
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    try:
        out = check(text, a.mode, contract, a.allow_placeholders)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        # 계약·렌더 구조가 예상과 다르면 traceback 대신 입력 오류(RC2)로 끝낸다.
        print(json.dumps({"result": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    out["rendered_sha256"] = hashlib.sha256(data).hexdigest()
    out["contract_sha256"] = hashlib.sha256(a.contract.read_bytes()).hexdigest()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
