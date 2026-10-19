"""#43 → #46 ROSA 전달 계약: 앱 전용 렌더(rosa-app)와 사전 자원 렌더(rosa-prereq)를 확인한다.

정적 시험은 어디서나 돈다. 실제 kustomize 렌더 시험은 kubectl이 있는 CI Ubuntu 러너에서만 돈다.
클러스터 접속·apply는 없다.
"""
from pathlib import Path
import copy
import shutil
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_delivery_render as cdr  # noqa: E402

DEPLOY = ROOT / "deploy"
BASE = DEPLOY / "base"
OCP = DEPLOY / "components" / "openshift"
APP = DEPLOY / "overlays" / "rosa-app"
PREREQ = DEPLOY / "overlays" / "rosa-prereq"
CONTRACT = yaml.safe_load((DEPLOY / "delivery" / "rosa.yaml").read_text(encoding="utf-8"))
APPROVED_HOST = "fds-api.apps.example.com"
# 전달 회차를 흉내 낸 계약: 시험용 승인 host(저장소 계약의 실제 승인 host와 별개).
DELIVERY = copy.deepcopy(CONTRACT)
DELIVERY["app"]["route_host"]["approved"] = APPROVED_HOST


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_all(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def ids(section):
    return {(o["apiVersion"], o["kind"], o["name"]) for o in CONTRACT[section]["objects"]}


def source_objects():
    """base + components/openshift 리소스(패치 전). 두 렌더와 제외 목록의 합이 이것과 같아야 한다."""
    docs = [d for f in load(BASE / "kustomization.yaml")["resources"] for d in load_all(BASE / f)]
    docs += [d for f in load(OCP / "kustomization.yaml")["resources"] for d in load_all(OCP / f)]
    return docs


def deleted(kust):
    out = set()
    for p in kust.get("patches", []):
        doc = yaml.safe_load(p["patch"])
        if isinstance(doc, dict) and doc.get("$patch") == "delete":
            out.add((doc["apiVersion"], doc["kind"], doc["metadata"]["name"]))
    return out


def synthetic_app_render():
    """kustomize 없이 rosa-app 결과를 흉내 낸다(체커 단위 시험용). 실제 렌더 시험은 아래 CI 클래스."""
    docs = []
    for d in copy.deepcopy(source_objects()):
        if cdr.ident(d) not in ids("app"):
            continue
        d["metadata"]["namespace"] = CONTRACT["namespace"]
        if d["kind"] == "Deployment":
            for c in d["spec"]["template"]["spec"]["containers"]:
                c["image"] = f"registry.example/fds/{c['image']}@sha256:{'a' * 64}"
            if d["metadata"]["name"] == "transaction-api":
                d["spec"]["template"]["metadata"]["labels"]["onprem-egress"] = "true"
        if d["kind"] == "Route":
            d["spec"]["host"] = APPROVED_HOST
        docs.append(d)
    return docs


def dump(docs):
    return yaml.safe_dump_all(docs, sort_keys=False)


class ContractShapeTests(unittest.TestCase):
    def test_renders_and_exclusion_partition_the_source_exactly(self):
        source = {cdr.ident(d) for d in source_objects()}
        excluded = {(o["apiVersion"], o["kind"], o["name"]) for o in CONTRACT["excluded_on_rosa"]}
        self.assertFalse(ids("app") & ids("prereq"))
        self.assertFalse((ids("app") | ids("prereq")) & excluded)
        self.assertEqual(ids("app") | ids("prereq") | excluded, source,
                         "base+openshift의 모든 객체가 앱 렌더·사전 자원·명시적 제외 중 정확히 한 곳에 있어야 한다")

    def test_overlays_delete_exactly_the_other_side(self):
        app, prereq = load(APP / "kustomization.yaml"), load(PREREQ / "kustomization.yaml")
        excluded = {(o["apiVersion"], o["kind"], o["name"]) for o in CONTRACT["excluded_on_rosa"]}
        self.assertEqual(deleted(app), ids("prereq") | excluded)
        self.assertEqual(deleted(prereq), ids("app") | excluded)
        for kust in (app, prereq):
            self.assertEqual(kust["namespace"], CONTRACT["namespace"])
            self.assertEqual(kust["resources"], ["../../base"])
            self.assertEqual(kust["components"], ["../../components/openshift"])
            self.assertFalse(kust["labels"][0]["includeSelectors"], "selector를 바꾸면 기존 ReplicaSet과 어긋난다")
        self.assertNotIn("lab-db", (APP / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("images", prereq)

    def test_app_overlay_labels_only_transaction_api_for_onprem_egress(self):
        targets = [p["target"]["name"] for p in load(APP / "kustomization.yaml")["patches"]
                   if p.get("target", {}).get("kind") == "Deployment"]
        self.assertEqual(targets, ["transaction-api"])
        self.assertEqual(CONTRACT["app"]["onprem_egress_label"], {"transaction-api": "true"})

    def test_repo_contract_route_host_is_pending_or_dns(self):
        approved = CONTRACT["app"]["route_host"]["approved"]
        self.assertTrue(approved == cdr.PENDING or cdr.dns_host(approved), approved)
        self.assertIn("Handoff 2", CONTRACT["app"]["route_host"]["source"])

    def test_app_overlay_sets_both_routes_to_contract_host(self):
        """2026-10-18: 승인 host 기록 뒤 rosa-app이 두 Route에 같은 값을 넣는다. 자리표시값은 component에만 남는다."""
        approved = CONTRACT["app"]["route_host"]["approved"]
        self.assertTrue(cdr.dns_host(approved), approved)
        patched = {}
        for p in load(APP / "kustomization.yaml")["patches"]:
            if p.get("target", {}).get("kind") == "Route":
                ops = yaml.safe_load(p["patch"])
                self.assertEqual([(o["op"], o["path"]) for o in ops], [("replace", "/spec/host")])
                patched[p["target"]["name"]] = ops[0]["value"]
        self.assertEqual(patched, {"transaction-api-api": approved, "transaction-api-readyz": approved})
        for d in load_all(OCP / "route.yaml"):
            self.assertEqual(d["spec"]["host"], "fds-api.route-host-input-pending.invalid")

    def test_contract_matches_base_service_accounts_and_secret_refs(self):
        for d in source_objects():
            if d["kind"] != "Deployment":
                continue
            name, spec = d["metadata"]["name"], d["spec"]["template"]["spec"]
            self.assertEqual(spec["serviceAccountName"], CONTRACT["app"]["service_accounts"][name])
            self.assertEqual(sorted(cdr.secret_names(spec)), CONTRACT["app"]["secret_refs"][name])


class CheckerTests(unittest.TestCase):
    def run_check(self, docs, mode="app", allow=False, contract=DELIVERY):
        return cdr.check(dump(docs), mode, contract, allow)

    def deployment(self, docs, name):
        return next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == name)

    def test_good_app_render_passes(self):
        out = self.run_check(synthetic_app_render())
        self.assertEqual(out["result"], "PASS", out["errors"])
        self.assertEqual(len(out["objects"]), 6)

    def test_extra_secret_or_rbac_is_rejected(self):
        for extra in ({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "x", "namespace": "fds-app"}},
                      {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
                       "metadata": {"name": "x", "namespace": "fds-app"}},
                      {"apiVersion": "v1", "kind": "ServiceAccount",
                       "metadata": {"name": "transaction-api-sa", "namespace": "fds-app"},
                       "automountServiceAccountToken": False}):
            out = self.run_check(synthetic_app_render() + [extra])
            self.assertEqual(out["result"], "FAIL")
            self.assertTrue(any("allowlist" in e for e in out["errors"]), out["errors"])

    def test_missing_object_is_rejected(self):
        docs = [d for d in synthetic_app_render() if d["kind"] != "Route"]
        self.assertTrue(any("missing" in e for e in self.run_check(docs)["errors"]))

    def test_cluster_scoped_and_wrong_namespace_are_rejected(self):
        docs = synthetic_app_render()
        docs[0]["metadata"]["namespace"] = "default"
        errors = self.run_check(docs + [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "x"}}])["errors"]
        self.assertTrue(any("namespace must be" in e for e in errors))
        self.assertTrue(any("cluster-scoped" in e for e in errors))

    def test_service_account_must_be_explicit_and_approved(self):
        for value in (None, "default", "fds-engine-sa"):
            docs = synthetic_app_render()
            spec = next(d for d in docs if d["metadata"]["name"] == "transaction-api"
                        and d["kind"] == "Deployment")["spec"]["template"]["spec"]
            if value is None:
                del spec["serviceAccountName"]
            else:
                spec["serviceAccountName"] = value
            self.assertTrue(any("serviceAccountName" in e for e in self.run_check(docs)["errors"]), value)

    def test_unapproved_secret_ref_tag_image_and_fixed_uid_are_rejected(self):
        docs = synthetic_app_render()
        eng = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "fds-engine")
        c = eng["spec"]["template"]["spec"]["containers"][0]
        c["env"] = [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "transaction-api-db-credentials", "key": "k"}}}]
        c["image"] = "registry.example/fds/fds-engine:latest"
        eng["spec"]["template"]["spec"]["securityContext"]["runAsUser"] = 10001
        errors = self.run_check(docs)["errors"]
        for needle in ("unapproved Secret", "pinned by digest", "runAsUser"):
            self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_onprem_egress_label_is_exact(self):
        docs = synthetic_app_render()
        eng = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "fds-engine")
        eng["spec"]["template"]["metadata"]["labels"]["onprem-egress"] = "true"
        self.assertTrue(any("onprem-egress" in e for e in self.run_check(docs)["errors"]))

    def test_image_must_be_exactly_name_at_64_hex_digest(self):
        """리뷰 B1: '@sha256:' 부분문자열만으로는 통과하지 않는다."""
        for bad in ("registry.example/fds/app@sha256:bad", f"registry.example/fds/app@sha256:{'A' * 64}",
                    f"registry.example/fds/app@sha256:{'a' * 63}", f"registry.example/fds/app@sha256:{'a' * 65}",
                    f"registry.example/fds/app@sha256:{'a' * 64} ", f"@sha256:{'a' * 64}", None):
            docs = synthetic_app_render()
            for c in self.deployment(docs, "transaction-api")["spec"]["template"]["spec"]["containers"]:
                c["image"] = bad
            out = self.run_check(docs)
            self.assertEqual(out["result"], "FAIL", bad)
            self.assertTrue(any("pinned by digest" in e for e in out["errors"]), (bad, out["errors"]))
        docs = synthetic_app_render()
        for c in self.deployment(docs, "transaction-api")["spec"]["template"]["spec"]["containers"]:
            c["image"] = f"registry.example:5000/fds/transaction-api@sha256:{'0123456789abcdef' * 4}"
        self.assertEqual(self.run_check(docs)["result"], "PASS")

    def test_route_host_empty_or_missing_is_rejected(self):
        """리뷰 B1: 빈 host·host 키 없음은 원소 1개짜리 집합으로 통과하지 않는다."""
        for mutate in (lambda spec: spec.__setitem__("host", ""), lambda spec: spec.pop("host"),
                       lambda spec: spec.__setitem__("host", None), lambda spec: spec.__setitem__("host", "Bad_Host")):
            docs = synthetic_app_render()
            for d in docs:
                if d["kind"] == "Route":
                    mutate(d["spec"])
            for allow in (False, True):
                out = self.run_check(docs, allow=allow)
                self.assertEqual(out["result"], "FAIL", (allow, out))
                self.assertTrue(any("nonempty DNS host" in e for e in out["errors"]), out["errors"])

    def test_image_pull_secrets_are_bound_to_approved_secret_refs(self):
        """리뷰 B2: imagePullSecrets도 승인 Secret 참조 목록과 대조한다."""
        docs = synthetic_app_render()
        self.deployment(docs, "transaction-api")["spec"]["template"]["spec"]["imagePullSecrets"] = [
            {"name": "unapproved-registry-secret"}]
        out = self.run_check(docs)
        self.assertEqual(out["result"], "FAIL")
        self.assertTrue(any("unapproved Secret" in e and "unapproved-registry-secret" in e for e in out["errors"]))
        allowed = copy.deepcopy(DELIVERY)
        allowed["app"]["secret_refs"]["transaction-api"].append("unapproved-registry-secret")
        self.assertEqual(self.run_check(docs, contract=allowed)["result"], "PASS", "계약에 넣은 이름만 허용")

    def test_route_host_must_equal_recorded_approved_host(self):
        """infra-rosa#5 v3.2 조건 2: 승인 host 1개와 다르면 첫 쓰기 전 STOP."""
        docs = synthetic_app_render()
        for d in docs:
            if d["kind"] == "Route":
                d["spec"]["host"] = "other.apps.example.com"
        out = self.run_check(docs)
        self.assertTrue(any("equal approved host" in e for e in out["errors"]), out["errors"])

    def test_pending_approved_host_blocks_delivery_but_not_ci_render_check(self):
        pending = copy.deepcopy(DELIVERY)
        pending["app"]["route_host"]["approved"] = cdr.PENDING
        out = self.run_check(synthetic_app_render(), contract=pending)
        self.assertEqual(out["result"], "FAIL")
        self.assertTrue(any("PENDING" in e for e in out["errors"]), out["errors"])
        self.assertEqual(self.run_check(synthetic_app_render(), allow=True, contract=pending)["result"], "PASS")
        broken = copy.deepcopy(DELIVERY)
        broken["app"]["route_host"]["approved"] = "not a host"
        errors = self.run_check(synthetic_app_render(), contract=broken)["errors"]
        self.assertTrue(any("not a DNS host" in e for e in errors), errors)

    def test_routes_must_share_one_host(self):
        docs = synthetic_app_render()
        next(d for d in docs if d["kind"] == "Route")["spec"]["host"] = "other.apps.example.com"
        self.assertTrue(any("one host" in e for e in self.run_check(docs)["errors"]))

    def test_route_tls_is_fixed_to_edge_default_cert(self):
        # routes/custom-host create는 인증서 필드 지정·변경도 허용한다(rosa#5 리뷰 6109978967 B1). 렌더에서 막는다.
        self.assertEqual(self.run_check(synthetic_app_render())["result"], "PASS")
        cases = (
            lambda tls: tls.update(certificate="-----BEGIN CERTIFICATE-----"),
            lambda tls: tls.update(key="k"),
            lambda tls: tls.update(externalCertificate={"name": "x"}),
            lambda tls: tls.update(termination="passthrough"),
            lambda tls: tls.pop("insecureEdgeTerminationPolicy"),
        )
        for mutate in cases:
            docs = synthetic_app_render()
            mutate(next(d for d in docs if d["kind"] == "Route")["spec"]["tls"])
            self.assertTrue(any("tls must be exactly" in e for e in self.run_check(docs)["errors"]), mutate)
        docs = synthetic_app_render()
        del next(d for d in docs if d["kind"] == "Route")["spec"]["tls"]
        self.assertTrue(any("tls must be exactly" in e for e in self.run_check(docs)["errors"]))

    def test_placeholders_block_delivery_unless_ci_flag(self):
        docs = synthetic_app_render()
        for d in docs:
            if d["kind"] == "Route":
                d["spec"]["host"] = "fds-api.route-host-input-pending.invalid"
        self.assertTrue(any("placeholder" in e for e in self.run_check(docs)["errors"]))
        # 승인 host가 PENDING인 계약에서는 CI 렌더 확인(--allow-placeholders)이 자리표시 host를 허용한다.
        pending = copy.deepcopy(CONTRACT)
        pending["app"]["route_host"]["approved"] = cdr.PENDING
        self.assertEqual(self.run_check(docs, allow=True, contract=pending)["result"], "PASS")
        self.assertEqual(self.run_check(docs, allow=True)["result"], "FAIL", "승인 host가 기록되면 자리표시 host는 불일치")

    def test_cli_exit_codes_and_hash_binding(self):
        import tempfile, json, contextlib, io
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "app.yaml")
            good.write_text(dump(synthetic_app_render()), encoding="utf-8")
            contract = Path(tmp, "rosa.yaml")
            contract.write_text(yaml.safe_dump(DELIVERY, sort_keys=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cdr.main(["--mode", "app", "--contract", str(contract), str(good)])
            out = json.loads(buf.getvalue())
            self.assertEqual((rc, out["result"], out["approved_route_host"]), (0, "PASS", APPROVED_HOST))
            import hashlib
            self.assertEqual(out["rendered_sha256"], hashlib.sha256(good.read_bytes()).hexdigest())
            self.assertEqual(out["contract_sha256"], hashlib.sha256(contract.read_bytes()).hexdigest())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cdr.main(["--mode", "prereq", "--contract", str(contract), str(good)]), 1)
                self.assertEqual(cdr.main(["--mode", "app", str(good)]), 1, "저장소 계약의 승인 host와 시험 host가 다름")
                self.assertEqual(cdr.main(["--mode", "app", str(Path(tmp, "missing.yaml"))]), 2)

    def test_cli_structural_error_is_rc2_not_traceback(self):
        import tempfile, json, contextlib, io
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "app.yaml")
            good.write_text(dump(synthetic_app_render()), encoding="utf-8")
            for name, body in (("no-app.yaml", "namespace: fds-app\n"),
                               ("bad-objects.yaml", "namespace: fds-app\napp:\n  objects: [1]\n")):
                contract = Path(tmp, name)
                contract.write_text(body, encoding="utf-8")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cdr.main(["--mode", "app", "--contract", str(contract), str(good)])
                self.assertEqual((rc, json.loads(buf.getvalue())["result"]), (2, "ERROR"), name)


class KustomizeRenderTests(unittest.TestCase):
    """실제 kustomize로 렌더한다(클러스터 접속 없음). kubectl이 있는 CI Ubuntu 러너에서 실행."""

    def render(self, overlay):
        kubectl = shutil.which("kubectl")
        if not kubectl:
            self.skipTest("kubectl 없음 — CI Ubuntu 러너에서 실행")
        done = subprocess.run([kubectl, "kustomize", str(overlay)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_app_render_matches_contract(self):
        text = self.render(APP)
        out = cdr.check(text, "app", CONTRACT, allow_placeholders=True)
        self.assertEqual(out["result"], "PASS", out["errors"])
        self.assertEqual(cdr.check(text, "app", CONTRACT)["result"], "FAIL", "자리표시값이 남은 렌더는 전달 거부")
        docs = [d for d in yaml.safe_load_all(text) if d]
        for d in docs:
            self.assertEqual(d["metadata"]["labels"]["project"], "fds-hybrid")
            if d["kind"] == "Deployment":
                self.assertEqual(d["spec"]["selector"]["matchLabels"], {"app": d["metadata"]["name"]})

    def test_prereq_render_matches_contract_with_openshift_policy_rules(self):
        text = self.render(PREREQ)
        out = cdr.check(text, "prereq", CONTRACT, allow_placeholders=True)
        self.assertEqual(out["result"], "PASS", out["errors"])
        pols = {d["metadata"]["name"]: d for d in yaml.safe_load_all(text) if d and d["kind"] == "NetworkPolicy"}
        api = pols["transaction-api-allow"]["spec"]
        self.assertEqual(api["ingress"][0]["ports"], [{"port": 8000, "protocol": "TCP"}])
        self.assertEqual(api["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"],
                         {"policy-group.network.openshift.io/ingress": ""})
        egress_ports = [p["port"] for rule in api["egress"] for p in rule["ports"]]
        self.assertEqual(sorted(set(egress_ports)), [53, 5353, 8001], "DB egress는 앱 NP가 아니라 플랫폼 03이 연다")
        eng = pols["fds-engine-allow"]["spec"]
        self.assertEqual([p["port"] for r in eng["ingress"] for p in r["ports"]], [8001])
        self.assertEqual(sorted({p["port"] for r in eng["egress"] for p in r["ports"]}), [53, 5353])


if __name__ == "__main__":
    unittest.main()
