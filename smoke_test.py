#!/usr/bin/env python3
"""Smoke test for the live ResidualVoid engine.

Usage
-----
  # Against a running local or production server:
  python smoke_test.py --url http://localhost:8080

  # Spin up a throwaway in-process server automatically (default):
  python smoke_test.py

  # Override the expected version:
  python smoke_test.py --expected-version 2.3.0

Exit codes
----------
  0 – all assertions passed
  1 – at least one assertion failed (safe to use as a deploy gate)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {FAIL}  {msg}")
        _failures.append(msg)


def _post(base_url: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _get(base_url: str, path: str) -> Dict[str, Any]:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# In-process server (used when no --url is supplied)
# ---------------------------------------------------------------------------

def _start_local_server() -> tuple[str, Any]:
    """Spin up a throwaway server on a free port and return (base_url, server)."""
    from residual_void.server import create_http_server

    server = create_http_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Brief pause so the server is ready
    time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

CANONICAL_DOC = (
    "A HyperSeed is the primordial compressed state from which a full residual "
    "network expands. It encodes the initial coherence signature, the ghost-tax "
    "baseline, and the Fibonacci shell geometry that governs wave projection. "
    "HyperSeeds are write-protected and serve as the origin anchor for all "
    "subsequent residuals in a CoherentVoid."
)

CANONICAL_QUERY = "What is a HyperSeed?"


def run_smoke_tests(base_url: str, expected_version: Optional[str]) -> None:
    print(f"\nSmoke-testing: {base_url}\n")

    # ------------------------------------------------------------------
    # 1. /status – reachability and version
    # ------------------------------------------------------------------
    print("── /status ──────────────────────────────────────")
    try:
        status = _get(base_url, "/status")
    except urllib.error.URLError as exc:
        _assert("GET /status reachable", False, str(exc))
        # Can't continue without a live server
        return

    _assert("GET /status returns JSON", isinstance(status, dict))
    _assert(
        "status.version present",
        "version" in status,
        f"keys: {list(status.keys())}",
    )
    if expected_version:
        _assert(
            f"version == {expected_version}",
            status.get("version") == expected_version,
            f"got {status.get('version')!r}",
        )
    _assert(
        "status.void.chain_ok is True",
        status.get("void", {}).get("chain_ok") is True,
        f"void status: {status.get('void')}",
    )

    # ------------------------------------------------------------------
    # 2. Seed canonical document
    # ------------------------------------------------------------------
    print("\n── /lock (seed canonical HyperSeed document) ────")
    try:
        lock_resp = _post(
            base_url,
            "/lock",
            {
                "text": CANONICAL_DOC,
                "domain": "smoke",
                "protect": True,
                "imprint_layer": "medium",
            },
        )
        _assert("POST /lock accepted", "result" in lock_resp, str(lock_resp))
    except Exception as exc:
        _assert("POST /lock succeeded", False, str(exc))

    # ------------------------------------------------------------------
    # 3. Canonical query
    # ------------------------------------------------------------------
    print("\n── /project (canonical query) ────────────────────")
    try:
        proj = _post(
            base_url,
            "/project",
            {"query": CANONICAL_QUERY, "mode": "exact", "top_k": 3},
        )
    except Exception as exc:
        _assert("POST /project succeeded", False, str(exc))
        return

    _assert("POST /project returns JSON", isinstance(proj, dict))
    _assert(
        "response contains 'results' key",
        "results" in proj,
        f"keys: {list(proj.keys())}",
    )

    results = proj.get("results", [])
    _assert("at least one result returned", len(results) >= 1, f"got {len(results)}")

    if results:
        top = results[0]
        top_text = (
            top.get("payload", "") or top.get("fragment", "") or top.get("text", "") or str(top)
        ).lower()
        _assert(
            "top result mentions 'HyperSeed'",
            "hyperseed" in top_text,
            f"top result: {str(top)[:120]}",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ResidualVoid live smoke test")
    parser.add_argument(
        "--url",
        default=None,
        help="Base URL of a running ResidualVoid server (e.g. https://prod.example.com). "
             "Omit to spin up a throwaway in-process server.",
    )
    # Default: read version from the installed package so a version bump
    # never requires editing this script.
    try:
        from residual_void import __version__ as _pkg_version
    except Exception:
        _pkg_version = None

    parser.add_argument(
        "--expected-version",
        default=_pkg_version,
        help=(
            "Semver string the /status endpoint must report. "
            "Defaults to the currently installed residual_void package version. "
            "Pass '' to skip the version check entirely."
        ),
    )
    args = parser.parse_args()

    server_handle = None
    if args.url:
        base_url = args.url.rstrip("/")
    else:
        print("No --url given – starting throwaway in-process server…")
        base_url, server_handle = _start_local_server()

    try:
        run_smoke_tests(base_url, args.expected_version or None)
    finally:
        if server_handle is not None:
            server_handle.shutdown()
            server_handle.server_close()

    print()
    if _failures:
        print(f"Result: {len(_failures)} failure(s):")
        for f in _failures:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print("Result: all checks passed ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
