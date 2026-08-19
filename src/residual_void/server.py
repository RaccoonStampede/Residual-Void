from __future__ import annotations

import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .merged import ResidualVoid
from .persistence import PersistentVoid

# Default storage path: configurable via RESIDUALVOID_STORAGE_PATH env var.
# Relative path resolves from the server's working directory (workspace root),
# which persists across in-deployment process restarts.
_DEFAULT_STORAGE_PATH = os.environ.get(
    "RESIDUALVOID_STORAGE_PATH", "residual_void_chain.jsonl"
)


def start_mdns_advertisement(port: int = 7700, name: str = "ResidualVoid"):
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        desc = {
            b"path": b"/",
            b"version": b"1.0",
            b"protocol": b"jsonrpc",
            b"service": b"residualvoid",
        }
        info = ServiceInfo(
            "_residualvoid._tcp.local.",
            f"{name}._residualvoid._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties=desc,
            server=f"{hostname}.local.",
        )
        zeroconf = Zeroconf()
        zeroconf.register_service(info)
        print(
            "[ResidualVoid] mDNS advertisement started: "
            f"{name}._residualvoid._tcp.local. on port {port}"
        )
        return zeroconf, info
    except Exception as e:  # pragma: no cover - network env-dependent
        print(f"[ResidualVoid] mDNS advertisement failed (non-fatal): {e}")
        return None, None


def _discovery_document(port: int = 7700) -> Dict[str, Any]:
    return {
        "service": "residualvoid",
        "version": "1.0",
        "protocol": "jsonrpc",
        "endpoints": {
            "lock": "lock",
            "project": "project",
            "inject": "inject",
            "status": "status",
        },
        "port": port,
    }


def _build_handler(runtime: ResidualVoid, snapshot_path: str = "void_snapshot.json"):
    class ResidualVoidHandler(BaseHTTPRequestHandler):
        def _write_json(self, payload: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # Readiness probes and browser clients may close after headers.
                # The response is already complete from the server's perspective;
                # do not turn a normal disconnect into a request-thread traceback.
                return

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/discover", "/.well-known/residualvoid.json"}:
                self._write_json(_discovery_document(port=self.server.server_port))
                return
            if path in {"/status", "/"}:
                self._write_json(runtime.status())
                return
            self._write_json({"error": "not_found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            payload = self._read_json()
            if path == "/lock":
                result = runtime.lock(
                    payload.get("text", ""),
                    domain=payload.get("domain", "general"),
                    protect=bool(payload.get("protect", True)),
                    shell=payload.get("shell"),
                    imprint_layer=payload.get("imprint_layer", "medium"),
                    coherence=float(payload.get("coherence", 0.85)),
                    identity=payload.get("identity"),
                    scale=float(payload.get("scale", 1.0)),
                    density=float(payload.get("density", 1.0)),
                    mass=(
                        float(payload["mass"])
                        if payload.get("mass") is not None
                        else None
                    ),
                    intent=str(payload.get("intent", "")),
                )
                response: Dict[str, Any] = {"result": result}
                if result == "locked":
                    info = runtime.last_locked_info()
                    if info is not None:
                        # Only surface family keys derived from structured
                        # TOPIC::TAG prefixes — fallback body-word families
                        # must not be exposed on an unauthenticated endpoint.
                        response["active"] = info["active"]
                        response["layer"] = info["layer"]
                        response["source_id"] = info["source_id"]
                        response["seed"] = info["seed"]
                        if info.get("family_tagged"):
                            response["family"] = info["family"]
                self._write_json(response)
                return
            if path == "/project":
                self._write_json(
                    runtime.project(
                        payload.get("query", ""),
                        mode=payload.get("mode", "exact"),
                        top_k=int(payload.get("top_k", 3)),
                    )
                )
                return
            if path == "/inject":
                self._write_json(
                    runtime.inject(
                        payload.get("full_text", ""),
                        domain=payload.get("domain", "DOC"),
                        title=payload.get("title", "SOURCE"),
                        protect=bool(payload.get("protect", True)),
                        identity=payload.get("identity"),
                        scale=float(payload.get("scale", 1.0)),
                        density=float(payload.get("density", 1.0)),
                        mass=(
                            float(payload["mass"])
                            if payload.get("mass") is not None
                            else None
                        ),
                        intent=str(payload.get("intent", "")),
                    )
                )
                return
            if path == "/status":
                self._write_json(runtime.status())
                return
            if path == "/clear":
                self._write_json(runtime.clear())
                return
            if path == "/snapshot":
                try:
                    saved_path = runtime.save_snapshot_file(snapshot_path)
                    self._write_json({"result": "saved", "path": saved_path})
                except Exception as exc:
                    self._write_json({"error": str(exc)}, status=500)
                return
            self._write_json({"error": "not_found"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ResidualVoidHandler


def create_http_server(
    host: str = "0.0.0.0",
    port: int = 7700,
    runtime: Optional[ResidualVoid] = None,
    snapshot_path: str = "void_snapshot.json",
) -> ThreadingHTTPServer:
    # Use PersistentVoid by default so residuals survive process restarts.
    # Callers may pass an explicit runtime (e.g. a bare ResidualVoid for
    # ephemeral testing) to override.
    if runtime is None:
        runtime = PersistentVoid(storage_path=_DEFAULT_STORAGE_PATH)
    return ThreadingHTTPServer((host, port), _build_handler(runtime, snapshot_path=snapshot_path))


def serve_residual_void(
    host: str = "0.0.0.0",
    port: int = 7700,
    runtime: Optional[ResidualVoid] = None,
    service_name: str = "ResidualVoid",
    snapshot_path: str = "void_snapshot.json",
) -> None:
    server = create_http_server(host=host, port=port, runtime=runtime, snapshot_path=snapshot_path)
    zc, mdns_info = start_mdns_advertisement(port=port, name=service_name)
    try:
        server.serve_forever()
    finally:
        if zc and mdns_info:
            try:
                zc.unregister_service(mdns_info)
            except Exception:
                pass
            zc.close()
        server.server_close()


def discover_and_connect(timeout: float = 3.0) -> dict:
    """
    Automatically find a ResidualVoid instance on the local network
    (or fall back to localhost) and return connection info.
    This is the function an LLM should call when told
    'go connect to the ResidualVoid network'.
    """
    found: Dict[str, Any] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info:
                addresses = info.parsed_addresses()
                if addresses:
                    found["host"] = addresses[0]
                    found["port"] = info.port
                    found["name"] = name

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    ServiceBrowser(zc, "_residualvoid._tcp.local.", Listener())
    time.sleep(timeout)
    zc.close()

    if not found:
        # Fallback to localhost
        found = {"host": "127.0.0.1", "port": 7700, "name": "localhost-fallback"}

    found["base_url"] = f"http://{found['host']}:{found['port']}"
    return found


def connect_to_residualvoid():
    info = discover_and_connect()
    print(f"[ResidualVoid] Connected to {info['base_url']}")
    return info
