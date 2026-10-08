"""Real Uvicorn configuration regression; mocked servers never bind sockets."""
import subprocess
import sys
from pathlib import Path


def test_metrics_config_preserves_main_api_access_logging():
    entrypoint = Path(__file__).resolve().parents[1] / "run.py"
    program = r'''
import ast, asyncio, logging, pathlib, sys
import uvicorn

# Execute the production main() without importing the DB-backed application.
tree = ast.parse(pathlib.Path(sys.argv[1]).read_text())
node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')
seen = []
class Server:
    def __init__(self, config):
        self.config = config
    async def serve(self):
        seen.append(self.config)
        assert logging.getLogger('uvicorn.access').isEnabledFor(logging.INFO)
        assert logging.getLogger('uvicorn.error').isEnabledFor(logging.INFO)
        logging.getLogger('uvicorn.access').info(
            '%s - "%s %s HTTP/%s" %d',
            '198.51.100.10:1234', 'GET', '/readyz?cutover=regression', '1.1', 200)

uvicorn.Server = Server
main_app, metrics_app = object(), object()
ns = dict(asyncio=asyncio, uvicorn=uvicorn, main_app=main_app, metrics_app=metrics_app,
          MAIN_PORT=8000, METRICS_PORT=9091)
exec(compile(ast.Module(body=[node], type_ignores=[]), sys.argv[1], 'exec'), ns)
asyncio.run(ns['main']())
assert [(c.port, c.app) for c in seen] == [(8000, main_app), (9091, metrics_app)]
print('BOTH_LISTENERS_KEEP_INFO')
'''
    result = subprocess.run([sys.executable, "-B", "-c", program, str(entrypoint)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BOTH_LISTENERS_KEEP_INFO" in result.stdout
    assert result.stdout.count("/readyz?cutover=regression") == 2
