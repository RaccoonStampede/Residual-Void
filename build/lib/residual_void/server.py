from __future__ import annotations

import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .merged import ResidualVoid


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


def _build_handler(runtime: ResidualVoid):
    class ResidualVoidHandler(BaseHTTPRequestHandler):
        def _write_json(self, payload: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
            if path == "/status":
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
                )
                self._write_json({"result": result})
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
                    )
                )
                return
            if path == "/status":
                self._write_json(runtime.status())
                return
            self._write_json({"error": "not_found"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ResidualVoidHandler


def create_http_server(
    host: str = "0.0.0.0",
    port: int = 7700,
    runtime: Optional[ResidualVoid] = None,
) -> ThreadingHTTPServer:
    service_runtime = runtime or ResidualVoid()
    return ThreadingHTTPServer((host, port), _build_handler(service_runtime))


def serve_residual_void(
    host: str = "0.0.0.0",
    port: int = 7700,
    runtime: Optional[ResidualVoid] = None,
    service_name: str = "ResidualVoid",
) -> None:
    server = create_http_server(host=host, port=port, runtime=runtime)
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
