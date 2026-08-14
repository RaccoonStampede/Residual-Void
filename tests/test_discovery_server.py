from __future__ import annotations

import json
import threading
from urllib.request import urlopen

from residual_void.server import create_http_server, discover_and_connect


def test_discover_and_connect_localhost_fallback(monkeypatch) -> None:
    class DummyZeroconf:
        def close(self) -> None:
            return

    monkeypatch.setattr("residual_void.server.Zeroconf", DummyZeroconf)
    monkeypatch.setattr("residual_void.server.ServiceBrowser", lambda *args, **kwargs: None)
    monkeypatch.setattr("residual_void.server.time.sleep", lambda _timeout: None)

    info = discover_and_connect(timeout=0.01)
    assert info["host"] == "127.0.0.1"
    assert info["port"] == 7700
    assert info["name"] == "localhost-fallback"
    assert info["base_url"] == "http://127.0.0.1:7700"


def test_discovery_endpoint_document() -> None:
    server = create_http_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/.well-known/residualvoid.json", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

    assert payload["service"] == "residualvoid"
    assert payload["protocol"] == "jsonrpc"
    assert payload["version"] == "1.0"
    assert payload["port"] == port
    assert payload["endpoints"] == {
        "lock": "lock",
        "project": "project",
        "inject": "inject",
        "status": "status",
    }
