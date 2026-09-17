"""
Entrypoint that runs fds-engine's main app and its dedicated metrics-only
app as two concurrent listeners in one process.

Why one process, two uvicorn.Server instances via asyncio.gather (instead
of two separate `uvicorn` CLI invocations / two containers): prometheus_client
Counters register against a single process-global REGISTRY. Two separate
processes would each hold their own empty registry, so the metrics port
would always report zero regardless of traffic the main port actually
served. This file is the container's CMD (see Dockerfile) in place of the
old `uvicorn app.main:app`.
"""
import asyncio
import os

import uvicorn

from app.main import app as main_app
from app.metrics import metrics_app

MAIN_PORT = int(os.environ.get("APP_PORT", "8001"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))


async def main() -> None:
    main_server = uvicorn.Server(
        uvicorn.Config(main_app, host="0.0.0.0", port=MAIN_PORT, log_level="info")
    )
    metrics_server = uvicorn.Server(
        uvicorn.Config(
            metrics_app, host="0.0.0.0", port=METRICS_PORT, log_level="warning"
        )
    )
    await asyncio.gather(main_server.serve(), metrics_server.serve())


if __name__ == "__main__":
    asyncio.run(main())
