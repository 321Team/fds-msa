"""D-03 loopback-only engine fixture; ordinary cases reach the real engine."""
import argparse
import datetime as dt
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import time

CASES = ('PRE', 'READ', 'READ_POST', 'HTTP', 'HTTP_POST', 'DB', 'DB_POST')


def validate_run(run):
    if not re.fullmatch(r'[0-9]{12}', run):
        raise ValueError('RUN must be KST YYYYMMDDHHMM')
    dt.datetime.strptime(run, '%Y%m%d%H%M')
    return run


def mode_for(run, payload):
    validate_run(run)
    prefix = 'SIM_d03_' + run + '_'
    account = payload.get('account_id', '')
    case = account[len(prefix):] if account.startswith(prefix) else ''
    if case not in CASES:
        raise ValueError('unexpected account')
    # The fixture cannot be switched to a different URL/host by its caller.
    return case, {'READ': 'read-timeout', 'HTTP': 'http-500'}.get(case, 'real-engine')


def make_server(run, port=18081):
    validate_run(run)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, body):
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected after the API's 2-second read timeout.

        def do_GET(self):
            self.reply(200 if self.path == '/readyz' else 404, b'{}')

        def do_POST(self):
            try:
                if self.path != '/evaluate':
                    raise ValueError('path')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('body size')
                self.connection.settimeout(4)
                raw = self.rfile.read(size)
                payload = json.loads(raw)
                case, mode = mode_for(run, payload)
                print(json.dumps({'event': 'request_received', 'run': run, 'case': case,
                                  'mode': mode, 'transaction_id': payload['transaction_id'],
                                  'at_utc': dt.datetime.now(dt.timezone.utc).isoformat()}), flush=True)
                if mode == 'read-timeout':
                    time.sleep(3.5)
                    self.reply(504, b'{"fixture":"delayed-response"}')
                elif mode == 'http-500':
                    self.reply(500, b'{"fixture":"D03_EXPECTED_ENGINE_HTTP500"}')
                    print(json.dumps({'event': 'http500_sent', 'run': run, 'case': case}), flush=True)
                else:
                    conn = http.client.HTTPConnection('127.0.0.1', 8001, timeout=4)
                    try:
                        conn.request('POST', '/evaluate', raw, {'Content-Type': 'application/json'})
                        response = conn.getresponse()
                        self.reply(response.status, response.read(32768))
                    finally:
                        conn.close()
            except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException):
                self.reply(502, b'{"fixture":"INVALID_OR_UPSTREAM_FAILED"}')

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    make_server(parser.parse_args().run).serve_forever()
