"""components/openshift·lab-db 계약을 정적으로 확인하고, 시험 DB schema 적용을 실제 PostgreSQL에서 확인한다."""
from pathlib import Path
import ast
import copy
import glob
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
BASE = DEPLOY / "base"
OCP = DEPLOY / "components" / "openshift"
LABDB = DEPLOY / "components" / "lab-db"
CHECK = DEPLOY / "overlays" / "openshift-render-check"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_all(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def base_docs():
    kust = load(BASE / "kustomization.yaml")
    return [d for f in kust["resources"] for d in load_all(BASE / f)]


def apply_patches(docs, kust):
    """kustomization의 JSON6902 add 패치만 적용한다(이 디렉터리에서 쓰는 형태)."""
    for p in kust.get("patches", []):
        ops = yaml.safe_load(p["patch"])
        t = p["target"]
        for doc in docs:
            if doc["kind"] != t["kind"] or doc["metadata"]["name"] != t.get("name", doc["metadata"]["name"]):
                continue
            for op in ops:
                assert op["op"] == "add", op
                parts = op["path"].strip("/").split("/")
                node = doc
                for key in parts[:-1]:
                    node = node[int(key)] if isinstance(node, list) else node[key]
                if parts[-1] == "-":
                    node.append(copy.deepcopy(op["value"]))
                else:
                    assert parts[-1] not in node, f"{op['path']} 이미 있음"
                    node[parts[-1]] = copy.deepcopy(op["value"])
    return docs


def rendered_policies():
    docs = base_docs()
    for comp in (OCP, LABDB):
        kust = load(comp / "kustomization.yaml")
        docs += [d for f in kust.get("resources", []) for d in load_all(comp / f)]
        apply_patches(docs, kust)
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == "NetworkPolicy"}


class OpenShiftComponentTests(unittest.TestCase):
    def test_component_kind_and_opt_in_scope(self):
        for comp in (OCP, LABDB):
            self.assertEqual(load(comp / "kustomization.yaml")["kind"], "Component")
        for kust in (BASE / "kustomization.yaml", DEPLOY / "overlays" / "p1-onprem" / "kustomization.yaml"):
            self.assertNotIn("lab-db", kust.read_text(encoding="utf-8"), f"{kust}: lab-db는 명시적 opt-in")
        text = (CHECK / "kustomization.yaml").read_text(encoding="utf-8")
        self.assertIn("apply하지 않는다", text)
        self.assertEqual(load(CHECK / "kustomization.yaml")["components"],
                         ["../../components/openshift", "../../components/lab-db"])

    def test_routes_expose_only_api_and_readyz_on_one_host(self):
        routes = [d for d in load_all(OCP / "route.yaml")]
        self.assertTrue(all(r["kind"] == "Route" for r in routes))
        self.assertEqual(sorted(r["spec"]["path"] for r in routes), ["/api", "/readyz"], "catch-all·/metrics Route 금지")
        self.assertEqual(len({r["spec"]["host"] for r in routes}), 1, "두 Route는 같은 host")
        svc = next(d for d in base_docs() if d["kind"] == "Service" and d["metadata"]["name"] == "transaction-api")
        http = next(p for p in svc["spec"]["ports"] if p["name"] == "http")
        self.assertEqual(http["targetPort"], 8000, "Route는 업무 포트로만")
        for r in routes:
            self.assertEqual(r["spec"]["to"], {"kind": "Service", "name": "transaction-api", "weight": 100})
            self.assertEqual(r["spec"]["port"], {"targetPort": "http"})
            self.assertEqual(r["spec"]["tls"]["termination"], "edge", "passthrough는 경로 라우팅 불가")
            self.assertEqual(r["spec"]["wildcardPolicy"], "None")

    def test_component_adds_no_fixed_uid_or_pull_secret(self):
        text = (OCP / "kustomization.yaml").read_text(encoding="utf-8") + (OCP / "route.yaml").read_text(encoding="utf-8")
        for banned in ("runAsUser", "runAsGroup", "fsGroup", "imagePullSecrets", "NodePort", "10.1.93."):
            self.assertNotIn(banned, text)


class KustomizeRenderTests(unittest.TestCase):
    """실제 kustomize로 렌더한다(클러스터 접속 없음). kubectl이 있는 CI Ubuntu 러너에서 실행."""

    def render(self, overlay):
        kubectl = shutil.which("kubectl")
        if not kubectl:
            self.skipTest("kubectl 없음 — CI Ubuntu 러너에서 실행")
        done = subprocess.run([kubectl, "kustomize", str(overlay)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return [d for d in yaml.safe_load_all(done.stdout) if d]

    def test_p1_onprem_renders_twelve_objects(self):
        docs = self.render(DEPLOY / "overlays" / "p1-onprem")
        self.assertEqual(len(docs), 12)
        self.assertTrue(all(d["metadata"]["namespace"] == "fds-app" for d in docs))

    def test_openshift_render_check_composes_base_and_components(self):
        docs = self.render(CHECK)
        kinds = sorted(f"{d['kind']}/{d['metadata']['name']}" for d in docs)
        cm = next(d["metadata"]["name"] for d in docs if d["kind"] == "ConfigMap")
        self.assertRegex(cm, r"^fds-lab-db-schema-[a-z0-9]{10}$")
        self.assertEqual(kinds, sorted([
            "ServiceAccount/transaction-api-sa", "Deployment/transaction-api", "Service/transaction-api",
            "ServiceAccount/fds-engine-sa", "Deployment/fds-engine", "Service/fds-engine",
            "NetworkPolicy/default-deny-all", "NetworkPolicy/transaction-api-allow", "NetworkPolicy/fds-engine-allow",
            "Route/transaction-api-api", "Route/transaction-api-readyz",
            "ServiceAccount/fds-lab-db-sa", "Deployment/fds-lab-db", "Service/fds-lab-db",
            "NetworkPolicy/fds-lab-db-allow", f"ConfigMap/{cm}"]))
        self.assertTrue(all(d["metadata"]["namespace"] == "fds-render-check" for d in docs))
        by = {(d["kind"], d["metadata"]["name"]): d for d in docs}
        db_pod = by[("Deployment", "fds-lab-db")]["spec"]["template"]["spec"]
        self.assertEqual(next(v for v in db_pod["volumes"] if v["name"] == "schema")["configMap"]["name"], cm)
        self.assertRegex(db_pod["containers"][0]["image"],
                         r"^quay\.io/sclorg/postgresql-16-c9s@sha256:[0-9a-f]{64}$")
        for name in ("transaction-api", "fds-engine"):
            image = by[("Deployment", name)]["spec"]["template"]["spec"]["containers"][0]["image"]
            self.assertRegex(image, rf"/fds/{name}@sha256:[0-9a-f]{{64}}$")
        rendered_nps = {n: by[("NetworkPolicy", n)] for k, n in by if k == "NetworkPolicy"}
        self.assertEqual(rendered_nps, rendered_policies_with_namespace("fds-render-check"))


def rendered_policies_with_namespace(ns):
    nps = rendered_policies()
    for d in nps.values():
        d["metadata"]["namespace"] = ns
    return nps


class LabDbComponentTests(unittest.TestCase):
    def setUp(self):
        self.docs = load_all(LABDB / "lab-db.yaml")
        self.kust = load(LABDB / "kustomization.yaml")

    def test_db_is_internal_pinned_and_secret_referenced(self):
        kinds = sorted(d["kind"] for d in self.docs)
        self.assertEqual(kinds, ["Deployment", "NetworkPolicy", "Service", "ServiceAccount"])
        svc = next(d for d in self.docs if d["kind"] == "Service")
        self.assertEqual(svc["spec"]["type"], "ClusterIP")
        self.assertNotIn("nodePort", str(svc))
        img = self.kust["images"][0]
        self.assertEqual(img["name"], "fds-lab-db")
        self.assertRegex(img["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("postgresql-16", img["newName"], "PG17 금지 — db01과 같은 16 계열")
        dep = next(d for d in self.docs if d["kind"] == "Deployment")
        pod = dep["spec"]["template"]["spec"]
        c = pod["containers"][0]
        self.assertEqual(c["image"], "fds-lab-db")
        for env in c["env"]:
            self.assertNotIn("value", env, "자격증명 값은 저장소에 두지 않는다")
            self.assertEqual(env["valueFrom"]["secretKeyRef"]["name"], "fds-lab-db-credentials")
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertNotIn("runAsUser", str(pod), "UID는 SCC가 배정")
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertTrue(all("emptyDir" in v or "configMap" in v for v in pod["volumes"]), "PVC·hostPath 없음")
        self.assertEqual(dep["spec"]["replicas"], 1)
        for d in self.docs:
            self.assertEqual(d["metadata"]["labels"]["app.kubernetes.io/part-of"], "fds-lab-db", "정리 selector")

    def test_only_transaction_api_reaches_db_and_engine_is_denied(self):
        nps = rendered_policies()
        db = nps["fds-lab-db-allow"]
        self.assertEqual(db["spec"]["ingress"], [{"from": [{"podSelector": {"matchLabels": {"app": "transaction-api"}}}],
                                                  "ports": [{"port": 5432, "protocol": "TCP"}]}])
        self.assertNotIn("egress", db["spec"])
        self.assertIn("Egress", db["spec"]["policyTypes"])
        api_eg = nps["transaction-api-allow"]["spec"]["egress"]
        self.assertIn({"to": [{"podSelector": {"matchLabels": {"app": "fds-lab-db"}}}],
                       "ports": [{"port": 5432, "protocol": "TCP"}]}, api_eg)
        engine = nps["fds-engine-allow"]["spec"]
        self.assertNotIn("5432", str(engine.get("egress", [])), "engine → DB 차단")
        self.assertNotIn("fds-lab-db", str(engine))
        self.assertEqual(engine["ingress"][0]["from"], [{"podSelector": {"matchLabels": {"app": "transaction-api"}}}])

    def test_schema_sql_is_bound_to_alembic_head(self):
        sql = (LABDB / "fds-schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
        recorded = dict(re.findall(r"^-- sha256 (\S+) ([0-9a-f]{64})$", sql, re.M))
        files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "alembic" / "versions").glob("*.py"))
        self.assertEqual(sorted(recorded), files, "migration 파일이 늘거나 줄면 SQL을 다시 생성")
        for name, digest in recorded.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest,
                             f"{name} 변경 — fds-schema.sql 재생성 필요")
        revs, downs = {}, set()
        for name in files:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            vals = {t.target.id: ast.literal_eval(t.value) for t in tree.body
                    if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name) and t.value is not None
                    and t.target.id in ("revision", "down_revision")}
            revs[vals["revision"]] = vals.get("down_revision")
            downs.add(vals.get("down_revision"))
        head = (set(revs) - downs).pop()
        self.assertIn(f"-- alembic head: {head}", sql)
        self.assertIn(f"SET version_num='{head}'", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))

    # --- 실제 PostgreSQL: postgresql-start 훅이 빈 DB에만 schema를 적용하고, 재시작에 멱등이며, 이상 상태에서 멈추는지.
    # 이미지(run-postgresql)는 create_users 뒤에 이 훅을 부르므로 계정·DB를 먼저 만든다. 이미지 자체의 시작 순서는
    # test_labdb_image_entrypoint.py(고정 digest 컨테이너)가 확인한다.
    @staticmethod
    def _pg_bindir():
        found = shutil.which("initdb")
        if found:
            return os.path.dirname(found)
        cands = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"))
        return os.path.dirname(cands[-1]) if cands else None

    def test_start_hook_is_idempotent_and_fails_closed_on_real_postgresql(self):
        bindir = self._pg_bindir()
        bash = shutil.which("bash")
        if not bindir or not bash or os.name == "nt":
            self.skipTest("PostgreSQL(initdb)·bash 없음 — CI Ubuntu 러너에서 실행")
        with tempfile.TemporaryDirectory(prefix="labdb") as root:
            data, sock = str(Path(root, "data")), str(Path(root, "s"))
            os.mkdir(sock)
            try:
                subprocess.run([os.path.join(bindir, "initdb"), "-D", data, "-A", "trust", "-U", "postgres",
                                "-E", "UTF8", "--no-sync"], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                self.skipTest(f"initdb 실행 불가: {e.stderr[-200:]!r}")
            pg_ctl = os.path.join(bindir, "pg_ctl")
            subprocess.run([pg_ctl, "-D", data, "-o", f"-c listen_addresses='' -k {sock} -p 54330",
                            "-l", str(Path(root, "pg.log")), "-w", "start"], check=True, capture_output=True)
            self.addCleanup(subprocess.run, [pg_ctl, "-D", data, "-m", "immediate", "stop"], capture_output=True)
            env = dict(os.environ, PGHOST=sock, PGPORT="54330", PGUSER="postgres",
                       PATH=bindir + os.pathsep + os.environ.get("PATH", ""))

            def psql(db, sql, user="postgres"):
                return subprocess.run([os.path.join(bindir, "psql"), "-X", "-q", "-U", user, "-d", db, "-v",
                                       "ON_ERROR_STOP=1", "-At", "-F", "|", "-c", sql],
                                      capture_output=True, text=True, env=env)

            def new_db(name):
                self.assertEqual(psql("postgres", f"create database {name} owner fds_lab").returncode, 0)

            def run_hook(db, sql_path=LABDB / "fds-schema.sql"):
                return subprocess.run([bash, "-c", f'set -eu; source "{LABDB / "10-fds-schema.sh"}"'],
                                      capture_output=True, text=True,
                                      env=dict(env, POSTGRESQL_DATABASE=db, POSTGRESQL_USER="fds_lab",
                                               FDS_SCHEMA_SQL=str(sql_path)))

            self.assertEqual(psql("postgres", "create role fds_lab login").returncode, 0)

            # (1) 빈 DB 첫 시작: 앱 계정 소유로 0003 적용
            new_db("fds_lab")
            first = run_hook("fds_lab")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("schema 0003 적용 완료", first.stdout)
            self.assertEqual(psql("fds_lab", "select version_num from alembic_version").stdout.strip(), "0003")
            self.assertEqual(psql("fds_lab", "select tableowner from pg_tables where tablename in "
                                  "('transactions','alembic_version') group by 1").stdout.strip(), "fds_lab")
            cols = psql("fds_lab", "select column_name||':'||data_type||':'||is_nullable from information_schema.columns "
                        "where table_name='transactions' order by ordinal_position").stdout.splitlines()
            self.assertEqual(cols, [
                "transaction_id:text:NO", "account_id:text:NO", "amount:numeric:NO", "currency:text:NO",
                "transaction_type:text:NO", "source_ip:text:YES", "occurred_at:timestamp with time zone:NO",
                "received_at:timestamp with time zone:NO", "fds_detected:boolean:YES", "fds_rules:jsonb:YES",
                "fds_evaluation_skipped:boolean:NO"])
            idx = psql("fds_lab", "select indexname from pg_indexes where tablename='transactions' order by 1")
            self.assertEqual(idx.stdout.splitlines(), ["idx_transactions_account_id",
                                                       "idx_transactions_account_type_time", "transactions_pkey"])
            ins = psql("fds_lab", "insert into transactions (transaction_id, account_id, amount, transaction_type, "
                       "occurred_at, received_at) values ('t1','a1',1,'TRANSFER',now(),now()) "
                       "returning fds_evaluation_skipped", user="fds_lab")
            self.assertEqual((ins.returncode, ins.stdout.splitlines()), (0, ["f"]), ins.stderr)

            # (2) 같은 데이터로 재시작: 재적용 없이 통과, 데이터 유지
            again = run_hook("fds_lab")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("재적용하지 않음", again.stdout)
            self.assertEqual(psql("fds_lab", "select count(*) from transactions").stdout.strip(), "1")

            # (3) 깨진 SQL 첫 시작: 실패·롤백, 같은 데이터로 재시작해도 다시 실패
            new_db("fds_bad")
            bad = Path(root, "bad.sql")
            bad.write_text("BEGIN;\nCREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);\nSELEC 1;\nCOMMIT;\n",
                           encoding="utf-8")
            for _ in range(2):
                failed = run_hook("fds_bad", bad)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("schema 적용 실패", failed.stderr)
                self.assertEqual(psql("fds_bad", "select count(*) from pg_tables where schemaname='public'")
                                 .stdout.strip(), "0")
            # (4) 고친 SQL로 같은 데이터 재시도: 복구
            fixed = run_hook("fds_bad")
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertEqual(psql("fds_bad", "select version_num from alembic_version").stdout.strip(), "0003")

            # (5) 부분 상태·다른 버전: 고치지 않고 멈춘다
            new_db("fds_partial")
            self.assertEqual(psql("fds_partial", "create table transactions (transaction_id text)").returncode, 0)
            partial = run_hook("fds_partial")
            self.assertNotEqual(partial.returncode, 0)
            self.assertIn("예상하지 못한 schema 상태: PARTIAL", partial.stderr)
            self.assertEqual(psql("fds_lab", "update alembic_version set version_num='0002'").returncode, 0)
            older = run_hook("fds_lab")
            self.assertNotEqual(older.returncode, 0)
            self.assertIn("예상하지 못한 schema 상태: VERSION:0002", older.stderr)


FAKE_OC = r'''#!/usr/bin/env bash
# 시험용 oc: 인자를 기록하고 FAKE_MODE에 따라 응답한다. 클러스터에 접속하지 않는다.
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$*" in
  *" delete "*) exit 0 ;;
  *" get deployment,replicaset,pod,"*)
    case "$FAKE_MODE" in
      sa_left) echo "serviceaccount/fds-lab-db-sa"; exit 0 ;;
      forbidden) echo 'Error from server (Forbidden): pods is forbidden' >&2; exit 1 ;;
    esac
    exit 0 ;;
  *" get networkpolicy transaction-api-allow "*)
    case "$FAKE_MODE" in
      policy_forbidden) echo 'Error from server (Forbidden)' >&2; exit 1 ;;
      policy_left) printf 'spec:\n  egress:\n  - to:\n    - podSelector:\n        matchLabels:\n          app: fds-lab-db\n' ;;
      *) printf 'spec:\n  egress:\n  - to:\n    - ipBlock:\n        cidr: 10.1.93.55/32\n' ;;
    esac
    exit 0 ;;
  *" get secret fds-lab-db-credentials "*)
    case "$*" in
      *POSTGRESQL_USER*) printf 'ZmRzX2xhYg==' ;; *POSTGRESQL_PASSWORD*) printf 'c2VjcmV0' ;; *) printf 'ZmRzX2xhYg==' ;;
    esac
    exit 0 ;;
  *" create secret "*) printf 'apiVersion: v1\nkind: Secret\n' ; exit 0 ;;
  *" rollout restart "*) [ "$FAKE_MODE" = restart_fail ] && exit 1; exit 0 ;;
  *) cat > /dev/null 2>&1 < /dev/null; exit 0 ;;
esac
'''


def readme_block(after):
    """README에서 `after` 문구 뒤 첫 bash 코드 블록을 꺼낸다(문서 명령 그대로 시험)."""
    text = (DEPLOY / "README.md").read_text(encoding="utf-8")
    start = text.index("```bash\n", text.index(after)) + len("```bash\n")
    return text[start:text.index("\n```", start)]


class LabDbRunbookCommandTests(unittest.TestCase):
    """리뷰 B3·B4: README 명령이 승인 context·namespace에만 작용하고, 정리 판정이 잔여·조회 오류를 구분하는지."""

    def setUp(self):
        self.bash = shutil.which("bash")
        if not self.bash or os.name == "nt":
            self.skipTest("bash 필요 — CI Ubuntu 러너에서 실행")
        self.root = Path(tempfile.mkdtemp(prefix="runbook"))
        self.addCleanup(shutil.rmtree, self.root, True)
        bindir = self.root / "bin"
        bindir.mkdir()
        (bindir / "oc").write_text(FAKE_OC, encoding="utf-8")
        os.chmod(bindir / "oc", 0o755)
        self.log = self.root / "oc.log"
        self.env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(self.log))

    def run_block(self, block, mode="ok", **extra):
        work = self.root / f"w-{mode}-{len(list(self.root.iterdir()))}"
        work.mkdir()
        env = dict(self.env, FAKE_MODE=mode, **extra)
        return subprocess.run([self.bash, "-c", block], cwd=work, capture_output=True, text=True, env=env)

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def assert_scoped(self):
        calls = self.calls()
        self.assertTrue(calls)
        for c in calls:
            self.assertIn("--context ctx-approved -n ns-approved", c, c)

    def test_every_lab_db_oc_command_in_readme_is_scoped(self):
        text = (DEPLOY / "README.md").read_text(encoding="utf-8")
        section = text[text.index("## 시험 DB"):text.index("### 아직 확인하지 못한 것")]
        oc_lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("oc ")]
        self.assertTrue(oc_lines)
        for line in oc_lines:
            self.assertRegex(line, r'^oc --context "\$CTX"( -n "\$NS")? ', line)
        self.assertIn('OC="oc --context $CTX -n $NS"', section)
        self.assertNotIn("get all", section, "`all`은 ServiceAccount를 포함하지 않는다")
        self.assertNotRegex(section, r"\| *grep -c", "조회 오류와 '없음'을 구분할 수 없는 파이프 판정 금지")

    def test_cleanup_distinguishes_four_cases(self):
        block = readme_block("### 정리와 readback")
        base = dict(CTX="ctx-approved", NS="ns-approved")
        ok = self.run_block(block, "ok", **base)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("CLEANUP_OK", ok.stdout)
        self.assert_scoped()
        for mode, expect in (("sa_left", "STOP: 잔여 자원 있음"), ("forbidden", "STOP: 잔여 조회 실패"),
                             ("policy_forbidden", "STOP: 정책 조회 실패"), ("policy_left", "STOP: 잔여 규칙 있음")):
            done = self.run_block(block, mode, **base)
            self.assertNotEqual(done.returncode, 0, mode)
            self.assertIn(expect, done.stdout, mode)
            self.assertNotIn("CLEANUP_OK", done.stdout, mode)
        unset = self.run_block(block, "ok", NS="ns-approved")
        self.assertNotEqual(unset.returncode, 0)
        self.assertIn("승인된 context 필요", unset.stderr)

    def test_rollback_targets_approved_namespace_and_stops_on_restart_failure(self):
        block = readme_block("**전환 실패 복구**")
        base = dict(CTX="ctx-approved", NS="ns-approved", PREV_OVERLAY="overlays/prev")
        ok = self.run_block(block, "ok", **base)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("ROLLBACK_APPLIED", ok.stdout)
        self.assertNotIn("c2VjcmV0", ok.stdout + ok.stderr)
        self.assertNotIn("secret", ok.stdout + ok.stderr, "복호화한 비밀번호를 출력하지 않는다")
        self.assert_scoped()
        steps = [key for c in self.calls() for key in ("create secret", "apply -k", "rollout restart", "rollout status")
                 if key in c]
        self.assertEqual(steps, ["create secret", "apply -k", "rollout restart", "rollout status"],
                         "Secret 복구 → overlay → restart → status 순서")
        failed = self.run_block(block, "restart_fail", **base)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("STOP: restart 실패", failed.stdout)
        self.assertNotIn("ROLLBACK_APPLIED", failed.stdout)
        missing = self.run_block(block, "ok", CTX="ctx-approved", NS="ns-approved")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("이전 revision의 overlay 경로 필요", missing.stderr)


if __name__ == "__main__":
    unittest.main()
