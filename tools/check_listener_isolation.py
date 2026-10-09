"""Bounded loopback HTTP checks inside an isolated candidate container.

Uses the running application entrypoint; no DB requests, remote hosts, or
redirect following. Response bodies are hashed, not emitted.
"""
import argparse
import datetime
import hashlib
import http.client
import json
import re
import time

SERVICES = {
    "transaction-api": (8000, 9091, "transaction_save_success_total"),
    "fds-engine": (8001, 9090, "fds_evaluated_total"),
}
MAX_BODY = 512 * 1024


def check(service, timeout=30, ports=None):
    main, metrics, counter = SERVICES[service]
    if ports is not None:  # Local loopback fixture ports, never a host override.
        main, metrics = ports
    deadline = time.monotonic() + timeout
    result = {"schema": "fds.candidate-listener-isolation.v1", "service": service,
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "container-loopback; no DB, cluster, policy or E2E validation",
              "requests": [], "result": "FAIL"}

    def request(port, method, path):
        remaining = deadline - time.monotonic()
        row = {"port": port, "method": method, "path": path}
        result["requests"].append(row)
        if remaining <= 0:
            row["error"] = "deadline_exceeded"
            return row, b""
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=min(1, remaining))
        try:
            conn.request(method, path)
            response = conn.getresponse()
            chunks = []
            size = 0
            while size <= MAX_BODY:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    row["error"] = "deadline_exceeded"
                    return row, b""
                if conn.sock is not None:
                    conn.sock.settimeout(min(1, remaining))
                chunk = response.read1(min(65536, MAX_BODY + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
            row.update(status=response.status, content_type=response.getheader("Content-Type", ""),
                       location_present=response.getheader("Location") is not None,
                       bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest())
            if len(body) > MAX_BODY:
                row["error"] = "body_limit_exceeded"
            return row, body
        except (OSError, http.client.HTTPException) as error:
            row["error"] = type(error).__name__
            return row, b""
        finally:
            conn.close()

    def ready(port, path):
        while True:
            row, body = request(port, "GET", path)
            if row.get("status") == 200 or row.get("error") == "body_limit_exceeded":
                return row, body
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return row, body
            time.sleep(min(0.1, remaining))

    def finish(reason):
        result["reason"] = reason
        result["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return result

    row, _ = ready(main, "/livez")
    if row.get("error") or row.get("status") != 200 or row["location_present"]:
        return finish("main_livez_not_ready")
    row, body = ready(metrics, "/metrics")
    if row.get("error") or row.get("status") != 200 or row["location_present"]:
        return finish("dedicated_metrics_not_ready")
    if not row["content_type"].startswith(("text/plain", "application/openmetrics-text")):
        return finish("dedicated_metrics_content_type")
    if (b"# TYPE " + counter.encode() + b" counter") not in body or not re.search(
            rb"(?m)^" + counter.encode() + rb"(?:\{[^\n]*\})? [0-9]", body):
        return finish("dedicated_application_counter_missing")

    for method in ("GET", "HEAD"):
        for path in ("/metrics", "/metrics/", "/%6detrics"):
            row, body = request(main, method, path)
            if row.get("error") or row.get("status") != 404 or row["location_present"] or b"# HELP" in body:
                return finish("business_metrics_not_isolated")
    result["result"] = "PASS"
    return finish("main_livez_200_dedicated_counter_200_business_metrics_404")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=tuple(SERVICES), required=True)
    args = parser.parse_args()
    result = check(args.service)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
