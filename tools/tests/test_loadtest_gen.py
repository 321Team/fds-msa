from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
import json
from unittest.mock import patch

from tools.loadtest.gen3 import main, run


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with self.server.lock:
            self.server.count += 1
            status = 201 if self.server.count <= self.server.ok_first else self.server.status
        time.sleep(self.server.delay)
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class LoadGeneratorTests(unittest.TestCase):
    def generate(self, delay, status=201, ok_first=0, **options):
        # 처음 ok_first건은 201, 그 뒤는 status로 응답한다.
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        server.delay, server.status, server.ok_first = delay, status, ok_first
        server.lock, server.count = threading.Lock(), 0
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        lines = []
        with tempfile.TemporaryDirectory() as out:
            code = run("SELFTEST", out, targets=("127.0.0.1",), port=server.server_address[1], emit=lines.append, **options)
            rows = [line.split() for line in (Path(out) / "requests.log").read_text(encoding="utf-8").splitlines()]
        return code, lines, rows

    @staticmethod
    def epoch(lines, word, stage=None):
        for line in lines:
            parts = line.split()
            if parts[1] == word and (stage is None or parts[2] == stage):
                return float(parts[-1])
        return None

    def test_normal_run_keeps_requests_inside_stage_windows(self):
        code, lines, rows = self.generate(
            0.0, stages=(("B", 20, 1.0), ("P", 40, 0.5)), idle=0.2, max_inflight=8, timeout=2, drain=1, progress=0.3)
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(row[4] == "201" for row in rows))
        for stage in ("B", "P"):
            start, end = self.epoch(lines, "START", stage), self.epoch(lines, "END", stage)
            self.assertTrue(all(start <= float(row[0]) <= end for row in rows if row[1] == stage))
        self.assertTrue(any(" DRAINED P " in line for line in lines))
        self.assertTrue(any(" IDLE END " in line for line in lines))
        self.assertTrue(lines[-1].split()[1:4] == ["DONE", "outstanding", "0"])

    def test_saturation_stops_without_spilling_into_next_stage(self):
        # 응답 1초, 동시 4개 -> 처리 용량 4 req/s < 목표 20 req/s
        code, lines, rows = self.generate(
            1.0, stages=(("B", 20, 2.0), ("P", 40, 1.0)), idle=0.2, max_inflight=4, timeout=3, drain=1, progress=10)
        self.assertEqual(code, 2)
        self.assertTrue(any("STOP LOAD_GENERATOR_SATURATED B" in line for line in lines))
        self.assertFalse(any(" START P " in line for line in lines))
        self.assertFalse(any(" IDLE START " in line for line in lines))
        stopped = self.epoch(lines, "STOP")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(float(row[0]) <= stopped for row in rows))
        self.assertTrue(lines[-1].split()[1:5] == ["FAIL", "LOAD_GENERATOR_SATURATED", "outstanding", "0"])

    def test_stage_not_drained_stops_before_next_stage(self):
        code, lines, rows = self.generate(
            1.5, stages=(("B", 2, 1.0), ("P", 40, 1.0)), idle=0.2, max_inflight=8, timeout=3, drain=0.3, progress=10)
        self.assertEqual(code, 2)
        self.assertTrue(any("STOP STAGE_NOT_DRAINED B" in line for line in lines))
        self.assertFalse(any(" START P " in line for line in lines))
        self.assertTrue(all(row[1] == "B" for row in rows))
        self.assertTrue(lines[-1].split()[1:5] == ["FAIL", "STAGE_NOT_DRAINED", "outstanding", "0"])

    def test_error_threshold_stops(self):
        code, lines, rows = self.generate(
            0.0, status=500, stages=(("B", 20, 2.0), ("P", 40, 1.0)), idle=0.2, max_inflight=8, timeout=2, drain=1,
            progress=0.5, error_stop=5)
        self.assertEqual(code, 2)
        self.assertTrue(any("STOP ERROR_THRESHOLD B" in line for line in lines))
        self.assertFalse(any(" START P " in line for line in lines))
        self.assertTrue(all(row[4] == "500" for row in rows))

    def test_error_threshold_in_stage_tail_stops(self):
        # 진행 기록 주기(10초)가 단계(1초)보다 길어 단계 안에서는 한 번도 검사하지 않는다.
        code, lines, rows = self.generate(
            0.0, status=500, stages=(("B", 20, 1.0), ("P", 40, 1.0)), idle=0.2, max_inflight=8, timeout=2, drain=1,
            progress=10, error_stop=5)
        self.assertEqual(code, 2)
        self.assertTrue(any("STOP ERROR_THRESHOLD B tail_errors" in line for line in lines))
        self.assertFalse(any(" DRAINED B " in line for line in lines))
        self.assertFalse(any(" START P " in line for line in lines))
        self.assertFalse(any(" IDLE START " in line for line in lines))
        self.assertTrue(all(row[1] == "B" and row[4] == "500" for row in rows))
        self.assertTrue(lines[-1].split()[1:5] == ["FAIL", "ERROR_THRESHOLD", "outstanding", "0"])

    def test_error_threshold_after_last_checkpoint_stops(self):
        # B 2초·진행 기록 1초: 31번째 요청(1.5초)부터 500이라 1초 기록 때는 오류가 없고,
        # 오류 10건이 모두 마지막 기록 뒤에 생긴다.
        code, lines, rows = self.generate(
            0.0, status=500, ok_first=30, stages=(("B", 20, 2.0), ("P", 40, 1.0)), idle=0.2, max_inflight=8,
            timeout=2, drain=1, progress=1.0, error_stop=5)
        checkpoints = [line for line in lines if " .. B sent " in line]
        self.assertEqual(len(checkpoints), 1)
        self.assertNotIn("500:", checkpoints[0])
        self.assertEqual(code, 2)
        self.assertTrue(any("STOP ERROR_THRESHOLD B tail_errors 10" in line for line in lines))
        self.assertFalse(any(" START P " in line for line in lines))
        self.assertFalse(any(" IDLE START " in line for line in lines))
        self.assertEqual(len(rows), 40)
        self.assertEqual(sum(1 for row in rows if row[4] == "500"), 10)
        self.assertTrue(lines[-1].split()[1:5] == ["FAIL", "ERROR_THRESHOLD", "outstanding", "0"])


class LoadProfileTests(unittest.TestCase):
    def test_legacy_cli_keeps_full_profile(self):
        with patch('tools.loadtest.gen3.run', return_value=2) as generate:
            self.assertEqual(main(['202610141300', 'existing-output']), 2)
        generate.assert_called_once_with('202610141300', 'existing-output')

    def test_regression_cli_claims_once_and_selects_8400_profile(self):
        with tempfile.TemporaryDirectory() as out, patch('tools.loadtest.gen3.run', return_value=2) as generate:
            self.assertEqual(main(['202610141300', out, '--profile', 'regression']), 2)
            generate.assert_called_once_with('202610141300', out, stages=(('B', 20, 120), ('P', 50, 120)))
            record = json.loads((Path(out) / 'regression-attempt.json').read_text(encoding='utf-8'))
            self.assertEqual(sum(rps * seconds for _, rps, seconds in record['stages']), 8400)
            self.assertEqual(record['idle_seconds'], 120)
            with self.assertRaises(SystemExit) as stopped:
                main(['202610141300', out, '--profile', 'regression'])
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(generate.call_count, 1)

    def test_existing_results_or_invalid_run_never_send_requests(self):
        with tempfile.TemporaryDirectory() as out, patch('tools.loadtest.gen3.run') as generate:
            for invalid in ['../../reuse', '20261014130', '２０２６１０１４１３００']:
                with self.subTest(run_id=invalid), self.assertRaises(SystemExit):
                    main([invalid, out, '--profile', 'regression'])
            (Path(out) / 'requests.log').write_text('preserve\n', encoding='utf-8')
            with self.assertRaises(SystemExit):
                main(['202610141300', out, '--profile', 'regression'])
            generate.assert_not_called()
            self.assertEqual((Path(out) / 'requests.log').read_text(encoding='utf-8'), 'preserve\n')


if __name__ == "__main__":
    unittest.main()
