from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import hashlib
import http.client
import json
import ssl
import tempfile
import threading
import unittest
import uuid

from tools.regression import p2e2e

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 21, 12, 40, tzinfo=KST)
BASE = "https://fds-api.apps.example.test"


class _FakeApi(BaseHTTPRequestHandler):
    """ROSA Route 뒤 transaction-api 흉내: 422 검증, R01·R02·R04·R07, engine 장애 시 fail-open, /metrics 비노출."""

    def _reply(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s = self.server
        if self.path == "/readyz":
            return self._reply(s.ready, {"status": "ready"})
        if self.path == "/metrics":
            return self._reply(s.metrics_code, {"metrics": "x"})
        return self._reply(404, {})

    def do_POST(self):
        s = self.server
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        with s.lock:
            s.posts += 1
            if s.posts == s.fail_on:
                return self._reply(500, {"detail": "transaction save failed"})
            if "amount" not in req or req.get("transaction_type") not in ("withdrawal", "transfer", "deposit"):
                return self._reply(422, {"detail": "validation"})
            occ = datetime.fromisoformat(req["occurred_at"]) if req.get("occurred_at") else s.now
            if occ.tzinfo is None:
                occ = occ.replace(tzinfo=KST)
            tid = str(uuid.uuid4())
            if s.engine_down:
                s.rows.append({"account": req["account_id"], "tid": tid, "type": req["transaction_type"],
                               "amount": req["amount"], "rules": None, "occ": occ.astimezone(KST)})
                return self._reply(201, {"transaction_id": tid, "fds_detected": None, "fds_rules": None,
                                         "fds_evaluation_skipped": True})
            prior = [r for r in s.rows if r["account"] == req["account_id"] and r["type"] == req["transaction_type"]]
            rules = set()
            if req["transaction_type"] == "withdrawal" and len(prior) >= 3:
                rules.add("R01")
            if req["amount"] >= 3000000:
                rules.add("R02")
            if 1 <= occ.astimezone(KST).hour < 5 and req["amount"] >= 1000000:
                rules.add("R04")
            if req["transaction_type"] == "transfer" and len(prior) >= 3 and sum(r["amount"] for r in prior) >= 2000000:
                rules.add("R07")
            s.rows.append({"account": req["account_id"], "tid": tid, "type": req["transaction_type"],
                           "amount": req["amount"], "rules": rules, "occ": occ.astimezone(KST)})
        self._reply(201, {"transaction_id": tid, "fds_detected": bool(rules), "fds_evaluation_skipped": False,
                          "fds_rules": [{"rule_id": r, "triggered": r in rules, "detail": None}
                                        for r in ("R01", "R02", "R04", "R07")]})

    def log_message(self, *args):
        pass


class P2RegressionToolTests(unittest.TestCase):
    def serve(self, ready=200, fail_on=0, engine_down=False, metrics_code=503):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeApi)
        server.daemon_threads = True
        server.ready, server.fail_on, server.engine_down, server.metrics_code = ready, fail_on, engine_down, metrics_code
        server.lock, server.posts, server.rows, server.now = threading.Lock(), 0, [], NOW
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    @staticmethod
    def caller(server, calls):
        """https_call 대신 가짜 서버로 보낸다(인증서 없는 단위 시험용). 호출 기록을 남긴다."""
        def call(base, cafile, method, path, payload=None, timeout=2):
            calls.append((method, path))
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=timeout)
            data = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, path, data, {"Content-Type": "application/json"} if data else {})
            resp = conn.getresponse()
            text = resp.read().decode("utf-8")
            conn.close()
            return resp.status, text
        return call

    def make_plan(self, root, run="202610201000", fixture="2026-10-20", cafile=None):
        plan_dir = str(Path(root, f"plan-{run}"))
        self.assertEqual(p2e2e.plan(plan_dir, run, fixture, BASE, cafile, emit=lambda line: None), 0)
        sha = Path(plan_dir, "criteria.sha256").read_text(encoding="utf-8").split()[0]
        return plan_dir, sha

    def execute(self, server, plan_dir, sha, group, out, calls=None, cafile=None):
        calls = [] if calls is None else calls
        lines = []
        code = p2e2e.run(plan_dir, out, group, sha, cafile=cafile, timeout=2, emit=lines.append,
                         call=self.caller(server, calls))
        return code, lines, calls

    def test_plan_is_offline_stable_and_pins_accounts_and_fixture_date(self):
        with tempfile.TemporaryDirectory() as root:
            a, sha_a = self.make_plan(str(Path(root, "a")))
            b, sha_b = self.make_plan(str(Path(root, "b")))
            crit = json.loads(Path(a, "criteria.json").read_text(encoding="utf-8"))
            raw = Path(a, "criteria.json").read_bytes()
        self.assertEqual(sha_a, sha_b)
        self.assertEqual(sha_a, hashlib.sha256(raw).hexdigest())
        self.assertEqual(crit["tool_sha256"], hashlib.sha256(Path(p2e2e.__file__).read_bytes()).hexdigest())
        posts = [c for c in crit["cases"] if c["method"] == "POST"]
        self.assertTrue(all(c["payload"]["account_id"].startswith("SIM_p2_202610201000_") for c in posts))
        p05 = next(c for c in crit["cases"] if c["id"] == "P05")
        self.assertEqual(p05["payload"]["occurred_at"], "2026-10-20T02:30:00+09:00")
        self.assertIn("SIM\\_p2\\_202610201000\\_%", crit["db_query"])

    def test_plan_rejects_http_path_bad_run_and_non_empty_dir(self):
        quiet = lambda line: None
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(p2e2e.plan(str(Path(root, "1")), "202610201000", "2026-10-20",
                                        "http://fds-api.example", emit=quiet), 2)
            self.assertEqual(p2e2e.plan(str(Path(root, "2")), "202610201000", "2026-10-20",
                                        BASE + "/api", emit=quiet), 2)
            self.assertEqual(p2e2e.plan(str(Path(root, "3")), "2026102010", "2026-10-20", BASE, emit=quiet), 2)
            self.assertEqual(p2e2e.plan(str(Path(root, "4")), "202610201000", "2026-13-40", BASE, emit=quiet), 2)
            Path(root, "5").mkdir()
            Path(root, "5", "old.txt").write_text("x", encoding="utf-8")
            self.assertEqual(p2e2e.plan(str(Path(root, "5")), "202610201000", "2026-10-20", BASE, emit=quiet), 2)

    def test_b1_b2_pass_and_ledger_refuses_resend(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            code1, _, calls1 = self.execute(server, plan_dir, sha, "B1", str(Path(root, "b1")))
            code2, _, calls2 = self.execute(server, plan_dir, sha, "B2", str(Path(root, "b2")))
            j1 = Path(root, "b1", "judge.txt").read_text(encoding="utf-8")
            j2 = Path(root, "b2", "judge.txt").read_text(encoding="utf-8")
            before = server.posts
            code3, lines3, calls3 = self.execute(server, plan_dir, sha, "B1", str(Path(root, "b1-again")))
        self.assertEqual((code1, code2), (0, 0))
        self.assertIn("== B1 11 PASS / 0 FAIL / 0 INFO", j1)
        self.assertIn("PASS P03-4 201 R01", j1)
        self.assertIn("PASS P04-4 201 R07", j1)
        self.assertIn("PASS P05 201 R04", j1)
        self.assertIn("== B2 14 PASS / 0 FAIL / 1 INFO", j2)
        self.assertIn("PASS X01 503", j2)
        self.assertEqual(calls1[0], ("GET", "/readyz"))
        self.assertEqual(len(calls2), 16)
        self.assertEqual(code3, 2)
        self.assertEqual(calls3, [])
        self.assertEqual(server.posts, before)
        self.assertTrue(any("GROUP_ALREADY_SENT" in line for line in lines3))

    def test_mismatched_criteria_tool_or_ca_stops_before_any_request(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            calls = []
            c1, l1, _ = self.execute(server, plan_dir, "0" * 64, "B1", str(Path(root, "o1")), calls)
            ca = Path(root, "ca.pem")
            ca.write_text("dummy", encoding="utf-8")
            c2, l2, _ = self.execute(server, plan_dir, sha, "B1", str(Path(root, "o2")), calls, cafile=str(ca))
            crit_path = Path(plan_dir, "criteria.json")
            crit = json.loads(crit_path.read_text(encoding="utf-8"))
            crit["tool_sha256"] = "1" * 64
            crit_path.write_text(json.dumps(crit), encoding="utf-8")
            new_sha = hashlib.sha256(crit_path.read_bytes()).hexdigest()
            c3, l3, _ = self.execute(server, plan_dir, new_sha, "B1", str(Path(root, "o3")), calls)
            ledger = Path(plan_dir, "ledger.jsonl").exists()
        self.assertEqual((c1, c2, c3), (2, 2, 2))
        self.assertTrue(l1[0].startswith("STOP CRITERIA_SHA_MISMATCH"))
        self.assertTrue(l2[0].startswith("STOP CAFILE_MISMATCH"))
        self.assertTrue(l3[0].startswith("STOP TOOL_SHA_MISMATCH"))
        self.assertEqual(calls, [])
        self.assertEqual(server.posts, 0)
        self.assertFalse(ledger)

    def test_real_https_call_tls_failure_stops_before_post(self):
        server = self.serve()  # 평문 HTTP 서버에 HTTPS로 붙으면 TLS 단계에서 실패한다
        with tempfile.TemporaryDirectory() as root:
            plan_dir = str(Path(root, "plan"))
            base = f"https://127.0.0.1:{server.server_address[1]}"
            self.assertEqual(p2e2e.plan(plan_dir, "202610201000", "2026-10-20", base, emit=lambda line: None), 0)
            sha = Path(plan_dir, "criteria.sha256").read_text(encoding="utf-8").split()[0]
            lines = []
            code = p2e2e.run(plan_dir, str(Path(root, "out")), "B1", sha, timeout=2, emit=lines.append)
            ledger = Path(plan_dir, "ledger.jsonl").exists()
        self.assertEqual(code, 2)
        self.assertEqual(server.posts, 0)
        self.assertFalse(ledger)
        self.assertTrue(any(line.startswith("STOP NOT_READY 0") for line in lines))

    def test_https_call_keeps_certificate_and_hostname_verification(self):
        seen = {}

        class Conn:
            def __init__(self, host, port, timeout=None, context=None):
                seen.update(host=host, port=port, context=context)

            def request(self, *args):
                raise ConnectionRefusedError()

        with mock.patch.object(p2e2e.http.client, "HTTPSConnection", Conn):
            code, err = p2e2e.https_call(BASE, None, "GET", "/readyz")
        self.assertEqual((code, err), (0, "ConnectionRefusedError"))
        self.assertEqual((seen["host"], seen["port"]), ("fds-api.apps.example.test", 443))
        self.assertTrue(seen["context"].check_hostname)
        self.assertEqual(seen["context"].verify_mode, ssl.CERT_REQUIRED)

    def test_unexpected_failopen_in_b1_stops(self):
        server = self.serve(engine_down=True)
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            code, lines, _ = self.execute(server, plan_dir, sha, "B1", str(Path(root, "b1")))
            judge = Path(root, "b1", "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 2)
        self.assertEqual(server.posts, 1)
        self.assertIn("STOP UNEXPECTED_SKIPPED P01", lines)
        self.assertIn("FAIL P02 - NOT_SENT", judge)

    def test_b3e_failopen_pass_and_injection_not_effective_stops(self):
        down = self.serve(engine_down=True)
        up = self.serve()
        with tempfile.TemporaryDirectory() as root:
            plan_a, sha_a = self.make_plan(str(Path(root, "a")))
            code_a, _, _ = self.execute(down, plan_a, sha_a, "B3E", str(Path(root, "a-out")))
            judge_a = Path(root, "a-out", "judge.txt").read_text(encoding="utf-8")
            plan_b, sha_b = self.make_plan(str(Path(root, "b")))
            code_b, lines_b, _ = self.execute(up, plan_b, sha_b, "B3E", str(Path(root, "b-out")))
        self.assertEqual(code_a, 0)
        self.assertIn("PASS E02 201 skipped", judge_a)
        self.assertEqual(code_b, 2)
        self.assertEqual(up.posts, 1)
        self.assertIn("STOP INJECTION_NOT_EFFECTIVE E01", lines_b)

    def test_5xx_stops_remaining_requests(self):
        server = self.serve(fail_on=3)
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            code, lines, _ = self.execute(server, plan_dir, sha, "B1", str(Path(root, "b1")))
        self.assertEqual(code, 2)
        self.assertEqual(server.posts, 3)
        self.assertIn("STOP HTTP_500 P03-1", lines)

    def test_metrics_exposed_through_route_is_fail(self):
        server = self.serve(metrics_code=200)
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            code, _, _ = self.execute(server, plan_dir, sha, "B2", str(Path(root, "b2")))
            judge = Path(root, "b2", "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("FAIL X01 200", judge)

    def test_rejudge_gives_same_result(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            out = str(Path(root, "b1"))
            self.execute(server, plan_dir, sha, "B1", out)
            first = Path(out, "judge.txt").read_text(encoding="utf-8")
            code = p2e2e.judge(plan_dir, out, emit=lambda line: None)
            second = Path(out, "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(first, second)

    @staticmethod
    def db_log(server, path):
        with open(path, "w", encoding="utf-8") as f:
            for r in server.rows:
                if r["rules"] is None:
                    det, skipped, rules = "", "t", "-"
                else:
                    det, skipped, rules = ("t" if r["rules"] else "f"), "f", ",".join(sorted(r["rules"])) or "-"
                f.write(f"{r['account']}|{r['tid']}|{r['type']}|{r['amount']}|{det}|{skipped}|{rules}|"
                        f"{r['occ'].strftime('%Y-%m-%d %H:%M:%S')}+09\n")

    def test_crosscheck_matches_and_detects_rule_time_and_extra_row(self):
        server = self.serve()
        quiet = lambda line: None
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            out = str(Path(root, "b1"))
            self.execute(server, plan_dir, sha, "B1", out)
            log = str(Path(root, "db.log"))
            self.db_log(server, log)
            self.assertEqual(p2e2e.crosscheck(plan_dir, out, log, emit=quiet), 0)
            server.rows[1]["rules"] = set()                                   # Rule 불일치
            self.db_log(server, log)
            self.assertEqual(p2e2e.crosscheck(plan_dir, out, log, emit=quiet), 1)
            server.rows[1]["rules"] = {"R02"}
            p05 = next(r for r in server.rows if r["account"].endswith("_P05"))
            p05["occ"] = p05["occ"] + timedelta(hours=1)                      # occurred_at 불일치
            self.db_log(server, log)
            self.assertEqual(p2e2e.crosscheck(plan_dir, out, log, emit=quiet), 1)
            p05["occ"] = p05["occ"] - timedelta(hours=1)
            server.rows.append(dict(server.rows[0], tid=str(uuid.uuid4())))  # 응답에 없는 행
            self.db_log(server, log)
            self.assertEqual(p2e2e.crosscheck(plan_dir, out, log, emit=quiet), 1)

    def test_crosscheck_accepts_failopen_null_detection(self):
        server = self.serve(engine_down=True)
        with tempfile.TemporaryDirectory() as root:
            plan_dir, sha = self.make_plan(root)
            out = str(Path(root, "b3e"))
            self.execute(server, plan_dir, sha, "B3E", out)
            log = str(Path(root, "db.log"))
            self.db_log(server, log)
            lines = []
            code = p2e2e.crosscheck(plan_dir, out, log, emit=lines.append)
        self.assertEqual(code, 0)
        self.assertIn("== B3E DB 2행 / 응답 201 2건 / 불일치 0", lines)


if __name__ == "__main__":
    unittest.main()
