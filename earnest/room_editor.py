"""Local room editor using the same room model and forward solver as the CLI."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

from .engine import RoomSpec, solve_room

_HTML = Path(__file__).with_name("web") / "room-editor.html"
_MAX_BODY = 1_000_000


def create_server(port: int = 8775) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: object) -> None:
            self._send(status, json.dumps(obj, allow_nan=False).encode(), "application/json; charset=utf-8")

        def _valid_host(self) -> bool:
            actual_port = self.server.server_address[1]
            return self.headers.get("Host", "").lower() in (f"127.0.0.1:{actual_port}", f"localhost:{actual_port}")

        def do_GET(self) -> None:
            if not self._valid_host():
                self.send_error(403)
            elif self.path == "/":
                self._send(200, _HTML.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/template":
                from .cli import _room_template
                self._json(200, _room_template())
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            actual_port = self.server.server_address[1]
            if not self._valid_host() or self.headers.get("Origin", "").lower() not in (f"http://127.0.0.1:{actual_port}", f"http://localhost:{actual_port}"):
                self.send_error(403)
                return
            if self.path not in ("/api/validate", "/api/solve", "/api/instructions", "/api/field"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= _MAX_BODY:
                    raise ValueError("room JSON must be between 1 byte and 1 MB")
                document = json.loads(self.rfile.read(length))
                field_options = document if self.path == "/api/field" else None
                room = RoomSpec.from_dict(document["room"] if field_options is not None else document)
                result = {"valid": True, "volume_m3": room.volume_m3,
                          "decay_estimates": room.decay_estimates(), "bands_hz": [125, 250, 500, 1000, 2000, 4000, 8000]}
                if self.path == "/api/field":
                    from .engine.field_grid import sample_room_field
                    result = sample_room_field(room, frequency_hz=field_options.get("frequency_hz", 1000),
                        grid_size=field_options.get("grid_size", 13), height_m=field_options.get("height_m"),
                        reflection_order=field_options.get("reflection_order", 1),
                        correlation_mode=field_options.get("correlation_mode", "independent"),
                        source_correlation=field_options.get("source_correlation"))
                if self.path == "/api/instructions":
                    from .room_instructions import make_instructions
                    result = make_instructions(document)
                if self.path == "/api/solve":
                    if len(room.sources) > 4 or len(room.receivers) > 4 or max(room.dimensions) > 100:
                        raise ValueError("interactive solve is limited to four sources, four receivers, and 100 m per dimension; use CLI for other cases")
                    solved = solve_room(room, fs=24000, max_order=min(room.controls.reflection_order, 3))
                    result.update({"pairs": [{k: v for k, v in pair.items() if k != "band_ir"}
                                             for pair in solved["source_receiver_pairs"]],
                                   "model_limits": solved["model_limits"],
                                   "interactive_reflection_order": solved["max_total_reflection_order"]})
                self._json(200, result)
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                self._json(400, {"error": str(exc)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int, open_browser: bool = False) -> None:
    server = create_server(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Room editor: {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
