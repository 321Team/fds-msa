"""
Dedicated metrics-only ASGI app, served on its own port (baseline dual-port
metrics contract: transaction-api main=8000, metrics=9091 — see
infra-kubernetes#7 SEC-05/manifests/03-networkpolicy.yaml and
manifests/02-securitycontext.yaml, GWONUK 2026-09-16).

This app defines no metrics of its own. prometheus_client registers
Counters (see app/main.py's TRANSACTION_SAVE_SUCCESS_TOTAL etc.) against a
process-global default REGISTRY, so as long as this listener runs in the
*same process* as app.main (see run.py), generate_latest() here reports
the counters updated by the business app, which has no /metrics route. Running the two
apps as separate OS processes would each start with an empty registry and
always report zero — this only works because run.py runs both as
concurrent asyncio servers inside one process.
"""
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


async def metrics(request):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


metrics_app = Starlette(routes=[Route("/metrics", metrics)])
