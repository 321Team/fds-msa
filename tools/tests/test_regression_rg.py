from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import tempfile
import threading
import unittest
import uuid

from tools.regression import rg

KST = timezone(timedelta(hours=9))


class _FakeApi(BaseHTTPRequestHandler):
    """transaction-api 흉내: 입력 검증(422)과 Rule R01·R02·R04·R07, 저장 행 기록."""

    def _reply(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply(self.server.ready, {"status": "ok"})

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
                # Match the approved rule source: naive input is treated as UTC.
                # This mock does not verify PostgreSQL session timezone/storage.
                occ = occ.replace(tzinfo=timezone.utc)
            prior = [r for r in s.rows if r["account"] == req["account_id"] and r["type"] == req["transaction_type"]]
            rules = set()
            if req["transaction_type"] == "withdrawal" and len(prior) >= 3 and "R01" not in s.disabled:
                rules.add("R01")
            if req["amount"] >= 3000000:
                rules.add("R02")
            if 1 <= occ.astimezone(KST).hour < 5 and req["amount"] >= 1000000:
                rules.add("R04")
            if req["transaction_type"] == "transfer" and len(prior) >= 3 and sum(r["amount"] for r in prior) >= 2000000:
                rules.add("R07")
            tid = str(uuid.uuid4())
            s.rows.append({"account": req["account_id"], "tid": tid, "type": req["transaction_type"],
                           "amount": req["amount"], "rules": rules, "occ": occ.astimezone(KST)})
        self._reply(201, {"transaction_id": tid, "fds_detected": bool(rules), "fds_evaluation_skipped": False,
                          "fds_rules": [{"rule_id": r, "triggered": r in rules, "detail": None}
                                        for r in ("R01", "R02", "R04", "R07")]})

    def log_message(self, *args):
        pass


class RegressionToolTests(unittest.TestCase):
    NOW = datetime(2026, 10, 5, 14, 0, tzinfo=KST)

    def serve(self, ready=200, fail_on=0, disabled=()):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeApi)
        server.daemon_threads = True
        server.ready, server.fail_on, server.disabled = ready, fail_on, set(disabled)
        server.lock, server.posts, server.rows, server.now = threading.Lock(), 0, [], self.NOW
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def execute(self, server, out):
        lines = []
        code = rg.run(out, targets=("127.0.0.1",) * 3, port=server.server_address[1], timeout=2, now=self.NOW,
                      emit=lines.append)
        return code, lines

    @staticmethod
    def db_log(server, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("2026-10-05T14:01:00+09:00\n")
            for r in server.rows:
                rules = ",".join(sorted(r["rules"])) or "-"
                f.write(f"{r['account']}|{r['tid']}|{r['type']}|{r['amount']}|{'t' if r['rules'] else 'f'}|f|{rules}|"
                        f"{r['occ'].strftime('%Y-%m-%d %H:%M:%S')}+09\n")
            f.write(f"rows|{len(server.rows)}\n")

    def test_normal_run_all_pass_and_criteria_first(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as out:
            code, lines = self.execute(server, out)
            judge = Path(out, "judge.txt").read_text(encoding="utf-8")
            crit = Path(out, "criteria.txt").read_bytes()
            sha_line = Path(out, "criteria.sha256").read_text(encoding="utf-8")
            meta = json.loads(Path(out, "meta.json").read_text(encoding="utf-8"))
            first = json.loads(Path(out, "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(code, 0)
        self.assertIn("== 24 PASS / 0 FAIL / 1 INFO", judge)
        self.assertIn("INFO I01 127.0.0.1 201\n", judge)
        self.assertEqual(sha_line, hashlib.sha256(crit).hexdigest() + "  criteria.txt\n")
        tool_sha = hashlib.sha256(Path(rg.__file__).read_bytes()).hexdigest()
        self.assertIn(f"SHA-256={tool_sha}".encode("utf-8"), crit)
        self.assertIn(b"RUN=202610051400", crit)
        self.assertLessEqual(meta["criteria_written_epoch"], first["t"])
        self.assertEqual(server.posts, 25)
        self.assertTrue(any(line.startswith("READYZ") for line in lines))

    def test_missed_rule_is_fail(self):
        server = self.serve(disabled=("R01",))
        with tempfile.TemporaryDirectory() as out:
            code, _ = self.execute(server, out)
            judge = Path(out, "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("FAIL P03-4 127.0.0.1 201", judge)
        self.assertIn("== 23 PASS / 1 FAIL / 1 INFO", judge)

    def test_5xx_stops_remaining_requests(self):
        server = self.serve(fail_on=3)
        with tempfile.TemporaryDirectory() as out:
            code, lines = self.execute(server, out)
            results = Path(out, "results.jsonl").read_text(encoding="utf-8").splitlines()
            judge = Path(out, "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 2)
        self.assertIn("STOP HTTP_500 P03-1", lines)
        self.assertEqual(server.posts, 3)
        self.assertEqual(len(results), 3)
        self.assertIn("FAIL P03-2 - - NOT_SENT", judge)

    def test_not_ready_blocks_all_writes(self):
        server = self.serve(ready=503)
        with tempfile.TemporaryDirectory() as out:
            code, lines = self.execute(server, out)
            wrote_results = Path(out, "results.jsonl").exists()
        self.assertEqual(code, 2)
        self.assertEqual(server.posts, 0)
        self.assertFalse(wrote_results)
        self.assertTrue(any(line.startswith("STOP NOT_READY") for line in lines))

    def test_non_empty_out_dir_is_refused(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as out:
            Path(out, "old.txt").write_text("x", encoding="utf-8")
            code, lines = self.execute(server, out)
            crit_exists = Path(out, "criteria.txt").exists()
        self.assertEqual(code, 2)
        self.assertEqual(server.posts, 0)
        self.assertFalse(crit_exists)
        self.assertTrue(lines[0].startswith("STOP OUT_DIR_NOT_EMPTY"))

    def test_rejudge_gives_same_result(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as out:
            self.execute(server, out)
            first = Path(out, "judge.txt").read_text(encoding="utf-8")
            code = rg.judge(out, emit=lambda line: None)
            second = Path(out, "judge.txt").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(first, second)

    def test_crosscheck_matches_and_detects_mismatch(self):
        server = self.serve()
        with tempfile.TemporaryDirectory() as out:
            self.execute(server, out)
            log = str(Path(out, "db.log"))
            quiet = lambda line: None
            self.db_log(server, log)
            self.assertEqual(rg.crosscheck(out, log, emit=quiet), 0)
            server.rows[1]["rules"] = set()                       # Rule 불일치
            self.db_log(server, log)
            self.assertEqual(rg.crosscheck(out, log, emit=quiet), 1)
            server.rows[1]["rules"] = {"R02"}
            removed = server.rows.pop(0)                          # DB 행 없음
            self.db_log(server, log)
            self.assertEqual(rg.crosscheck(out, log, emit=quiet), 1)
            server.rows.insert(0, removed)
            server.rows.append(dict(removed, tid=str(uuid.uuid4())))  # 응답에 없는 행
            self.db_log(server, log)
            self.assertEqual(rg.crosscheck(out, log, emit=quiet), 1)

    @staticmethod
    def evidence_fixture(out):
        """Synthetic complete evidence; no HTTP, PostgreSQL or operational writes."""
        run, today = '202610101400', '2026-10-10'
        tool_sha = hashlib.sha256(Path(rg.__file__).read_bytes()).hexdigest()
        criteria = rg.criteria_text(run, today, tool_sha, ('127.0.0.1',), 30080)
        Path(out, 'criteria.txt').write_text(criteria, encoding='utf-8')
        meta = {'run': run, 'today': today, 'tool_sha256': tool_sha, 'targets': ['127.0.0.1'], 'port': 30080,
                'criteria_sha256': hashlib.sha256(Path(out, 'criteria.txt').read_bytes()).hexdigest()}
        Path(out, 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
        records, rows = [], []
        for n, (cid, payload, expected) in enumerate(rg.cases(run, today)):
            triggered = expected if isinstance(expected, frozenset) else frozenset()
            tid = str(uuid.UUID(int=n + 1))
            body = {'transaction_id': tid, 'fds_detected': bool(triggered), 'fds_evaluation_skipped': False,
                    'fds_rules': [{'rule_id': rid, 'triggered': rid in triggered, 'detail': None}
                                  for rid in ('R01', 'R02', 'R04', 'R07')]}
            code = 422 if expected == 'HTTP422' else 201
            records.append({'case': cid, 'worker': '127.0.0.1', 'http': code, 'body': json.dumps(body)})
            if code == 201:
                rows.append('|'.join([payload['account_id'], tid, payload['transaction_type'], str(payload['amount']),
                                      't' if triggered else 'f', 'f', ','.join(sorted(triggered)) or '-',
                                      '2026-10-10 14:00:00+09']))
        RegressionToolTests.write_results(out, records)
        Path(out, 'db.log').write_text('\n'.join(rows) + '\n', encoding='utf-8')
        return records, rows, meta

    @staticmethod
    def write_results(out, records):
        Path(out, 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')

    def test_synthetic_complete_evidence_matches_without_network(self):
        with tempfile.TemporaryDirectory() as out:
            self.evidence_fixture(out)
            self.assertEqual(rg.judge(out, emit=lambda _: None), 0)
            self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 0)

    def test_four_rule_contract_and_boolean_types_are_required(self):
        with tempfile.TemporaryDirectory() as out:
            records, _, _ = self.evidence_fixture(out)
            valid = json.loads(records[0]['body'])
        broken = []
        broken.append(dict(valid, fds_rules=[]))
        broken.append(dict(valid, fds_rules=valid['fds_rules'][:3]))
        broken.append(dict(valid, fds_rules=[valid['fds_rules'][0]] * 4))
        broken.append(dict(valid, fds_rules=[dict(r, rule_id='UNKNOWN') for r in valid['fds_rules']]))
        broken.append(dict(valid, fds_rules=[dict(r, triggered=0) for r in valid['fds_rules']]))
        broken.append(dict(valid, fds_detected=0))
        broken.append(dict(valid, fds_detected='false'))
        broken.append(dict(valid, fds_detected=True))
        broken.append(dict(valid, fds_evaluation_skipped=0))
        broken.append(dict(valid, transaction_id=''))
        for body in broken:
            with self.subTest(body=body):
                self.assertEqual(rg.judge_one(frozenset(), 201, json.dumps(body))[0], 'FAIL')

    def test_duplicate_case_cannot_hide_prior_failure_and_preserves_old_judgement(self):
        with tempfile.TemporaryDirectory() as out:
            records, _, _ = self.evidence_fixture(out)
            correct = dict(records[1])
            failed_body = json.loads(records[0]['body'])
            failed_body['transaction_id'] = json.loads(records[1]['body'])['transaction_id']
            records[1]['body'] = json.dumps(failed_body)
            records.append(correct)
            self.write_results(out, records)
            Path(out, 'judge.txt').write_bytes(b'ORIGINAL-JUDGEMENT\n')
            self.assertEqual(rg.judge(out, emit=lambda _: None), 2)
            self.assertEqual(Path(out, 'judge.txt').read_bytes(), b'ORIGINAL-JUDGEMENT\n')
            self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)

    def test_unknown_case_and_target_are_refused(self):
        for field, value in [('case', 'UNKNOWN'), ('worker', '192.0.2.99'), ('http', True), ('http', -1)]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as out:
                records, _, _ = self.evidence_fixture(out)
                records[0][field] = value
                self.write_results(out, records)
                self.assertEqual(rg.judge(out, emit=lambda _: None), 2)
                self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)

    def test_distinct_cases_cannot_share_transaction_id(self):
        with tempfile.TemporaryDirectory() as out:
            records, _, _ = self.evidence_fixture(out)
            second = json.loads(records[1]['body'])
            second['transaction_id'] = json.loads(records[0]['body'])['transaction_id']
            records[1]['body'] = json.dumps(second)
            self.write_results(out, records)
            self.assertEqual(rg.judge(out, emit=lambda _: None), 2)
            self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)

    def test_empty_and_partial_responses_cannot_pass_db_crosscheck(self):
        for count in (0, 1, 24):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as out:
                records, _, _ = self.evidence_fixture(out)
                self.write_results(out, records[:count])
                Path(out, 'db.log').write_text('rows|0\n', encoding='utf-8')
                self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)
                self.assertEqual(rg.judge(out, emit=lambda _: None), 1)

    def test_duplicate_and_malformed_db_rows_are_refused(self):
        for extra in ('duplicate', 'malformed'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as out:
                _, rows, _ = self.evidence_fixture(out)
                rows.append(rows[0] if extra == 'duplicate' else 'SIM_rg_202610101400_bad|broken')
                Path(out, 'db.log').write_text('\n'.join(rows) + '\n', encoding='utf-8')
                self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)

    def test_failed_api_case_cannot_become_success_by_matching_bad_database_row(self):
        with tempfile.TemporaryDirectory() as out:
            records, rows, _ = self.evidence_fixture(out)
            body = json.loads(records[1]['body'])
            body['fds_detected'] = False
            for rule in body['fds_rules']:
                rule['triggered'] = False
            records[1]['body'] = json.dumps(body)
            row = rows[1].split('|')
            row[4], row[6] = 'f', '-'
            rows[1] = '|'.join(row)
            self.write_results(out, records)
            Path(out, 'db.log').write_text('\n'.join(rows) + '\n', encoding='utf-8')
            self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)

    def test_source_criteria_and_metadata_binding_before_rejudgement(self):
        for change in ('tool', 'criteria', 'run', 'date', 'targets', 'rehashed-criteria'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as out:
                _, _, meta = self.evidence_fixture(out)
                if change == 'tool':
                    meta['tool_sha256'] = '0' * 64
                elif change in ('criteria', 'rehashed-criteria'):
                    Path(out, 'criteria.txt').write_text('CHANGED CRITERIA\n', encoding='utf-8')
                    if change == 'rehashed-criteria':
                        meta['criteria_sha256'] = hashlib.sha256(Path(out, 'criteria.txt').read_bytes()).hexdigest()
                elif change == 'run':
                    meta['run'] = '202610101500'
                elif change == 'date':
                    meta['today'] = '2026-10-11'
                elif change == 'targets':
                    meta['targets'] = ['192.0.2.99']
                Path(out, 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
                Path(out, 'judge.txt').write_bytes(b'ORIGINAL\n')
                self.assertEqual(rg.judge(out, emit=lambda _: None), 2)
                self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)
                self.assertEqual(Path(out, 'judge.txt').read_bytes(), b'ORIGINAL\n')

    def test_corrupt_json_and_missing_input_stop_without_rewriting_original(self):
        for path in ('meta.json', 'results.jsonl', 'criteria.txt'):
            for operation in ('corrupt', 'missing'):
                with self.subTest(path=path, operation=operation), tempfile.TemporaryDirectory() as out:
                    self.evidence_fixture(out)
                    if operation == 'corrupt':
                        Path(out, path).write_text('{BROKEN', encoding='utf-8')
                    else:
                        Path(out, path).unlink()
                    Path(out, 'judge.txt').write_bytes(b'ORIGINAL\n')
                    self.assertEqual(rg.judge(out, emit=lambda _: None), 2)
                    self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 2)
                    self.assertEqual(Path(out, 'judge.txt').read_bytes(), b'ORIGINAL\n')

    def test_db_crosscheck_does_not_modify_evidence(self):
        with tempfile.TemporaryDirectory() as out:
            self.evidence_fixture(out)
            before = {p.name: p.read_bytes() for p in Path(out).iterdir()}
            self.assertEqual(rg.crosscheck(out, str(Path(out, 'db.log')), emit=lambda _: None), 0)
            after = {p.name: p.read_bytes() for p in Path(out).iterdir()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
