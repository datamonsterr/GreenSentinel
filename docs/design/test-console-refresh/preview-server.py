"""Serve the design preview and an existing local MapLibre installation only."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8766)
parser.add_argument("--maplibre", type=Path, required=True, help="Existing maplibre-gl/dist directory")
args = parser.parse_args()


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript"}

    def translate_path(self, path):
        clean = path.split("?")[0]
        if clean.startswith("/maplibre/"):
            candidate = (args.maplibre / clean.removeprefix("/maplibre/")).resolve()
            if candidate.is_relative_to(args.maplibre.resolve()):
                return str(candidate)
            return str(ROOT / "__not_found__")
        return super().translate_path(path)

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)


print(f"Preview: http://127.0.0.1:{args.port}/preview.html", flush=True)
ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
