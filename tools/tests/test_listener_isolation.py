"""Real local HTTP fixtures exercise fail-closed response handling."""
import importlib.util
import pathlib
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPEC = importlib.util.spec_from_file_location("listener_check", pathlib.Path(__file__).parents[1] / "check_listener_isolation.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
METRICS = b"# HELP transaction_save_success_total Saved\n# TYPE transaction_save_success_total counter\ntransaction_save_success_total 0.0\n"


@contextmanager
def fixture(metrics=False, main_status=404, metrics_body=METRICS, unavailable=False):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path))
            code = 200 if self.path == "/livez" or metrics else main_status
            body = metrics_body if metrics else b'{"status":"ok"}' if self.path == "/livez" else b"Not Found"
            if unavailable:
                code = 503
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/redirect-target")
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        do_HEAD = do_GET
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ListenerIsolationTests(unittest.TestCase):
    def run_case(self, **kwargs):
        with fixture(main_status=kwargs.pop("main_status",404)) as (main, seen), fixture(metrics=True, **kwargs) as (metrics, _):
            result = CHECK.check("transaction-api", timeout=0.3, ports=(main,metrics))
        return result, seen

    def test_isolated_ports_include_six_negative_requests(self):
        result, _ = self.run_case()
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(len(result["requests"]), 8)
        self.assertEqual(sum(r["method"]=="HEAD" for r in result["requests"]), 3)

    def test_main_metrics_200_fails(self):
        result, _ = self.run_case(main_status=200)
        self.assertEqual(result["reason"], "business_metrics_not_isolated")
        self.assertEqual(result["result"], "FAIL")

    def test_redirect_is_not_followed_or_accepted(self):
        result, seen = self.run_case(main_status=302)
        self.assertEqual(result["result"], "FAIL")
        self.assertNotIn(("GET","/redirect-target"), seen)

    def test_200_without_application_counter_fails(self):
        result, _ = self.run_case(metrics_body=b"# HELP unrelated Metric\n")
        self.assertEqual(result["reason"], "dedicated_application_counter_missing")

    def test_unavailable_metrics_fails_with_bounded_deadline(self):
        result, _ = self.run_case(unavailable=True)
        self.assertEqual(result["reason"], "dedicated_metrics_not_ready")
        self.assertEqual(result["result"], "FAIL")

    def test_oversized_body_fails_closed(self):
        result, _ = self.run_case(metrics_body=b"x"*(CHECK.MAX_BODY+1))
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["requests"][-1]["error"], "body_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
