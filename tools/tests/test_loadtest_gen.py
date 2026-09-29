from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest

from tools.loadtest.gen3 import run


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        time.sleep(self.server.delay)
        self.send_response(self.server.status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class LoadGeneratorTests(unittest.TestCase):
    def generate(self, delay, status=201, **options):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        server.delay, server.status = delay, status
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


if __name__ == "__main__":
    unittest.main()
