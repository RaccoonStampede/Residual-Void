# ResidualVoid v2.3.0 – Unified Production Runtime

**Release Date:** 2026-08-19
**Status:** Production Ready ✅

## Overview

ResidualVoid v2.3 adds complete, grounded Synthesize Intent Cells while preserving the
Source-only Exact path, existing multi-item Synthesize behavior, and default-off Pure-Harness
isolation.

### v2.3 Intent Cell build

- Structured query branches for WHY, WHEN, HOW, WHO, WHAT, definition, mechanism, diagnosis,
  and general factual questions
- Complete sentence-safe primary Shadow output with up to two compatible supporting Shadows
- No generated connective prose, paraphrases, or mid-sentence truncation
- Intent/topic preference only after target, grounding, seed, frame, carrier, and
  primary-admission gates
- Exact-boundary, refusal, multi-item, Source/Shadow, and Pure-Harness regression coverage

ResidualVoid v2.2 promotes parity with Unified Master ranking/synthesis and persistence features while keeping the modular package API.
All advanced capabilities previously delivered in `residual_void_production.py` are now
the package default, accessible via `pip install .` and `from residual_void import ...`.

## What's Included

### Included v2.2 Runtime Capabilities
- **Hierarchical edge-nulling Pi-Helix extractor (v2)** — Schumann carriers + golden-ratio drives
- **Nested geometric shells + Fibonacci placement** — shell-aware coherence tracking
- **Hierarchical message-passing** — Laplacian spectrum (Fiedler eigenvalue) for graph analysis
- **Fast / Medium / Deep imprint layers** — multi-pass coherence refinement
- **Ghost tax + ethical tilt** — irreducible generative leakage prevents sterile lock
- **God-zone regulation** — autonomous drift stabilization near 0.008
- **Binary residual path** — full binary payload support (SHA-256 + Blake2b + HMAC)
- **Unlimited private mergers** — `ResidualNetworkManager` with isolated secrets, key rotation, nonce replay protection
- **ResidualGeometry + ResidualFieldMind** — geometry and mind layers available on default import path
- **Intent-aware synthesize ranking** — fuzzy token recovery + resonance + Bellman value updates
- **Complete Synthesize Intent Cells** — grounded, sentence-safe answers for interrogative
  and diagnostic query branches
- **Persistent append-only runtime** — `PersistentVoid` JSONL chain support
- **Snapshot / restore / drift audit** — reproducibility and stability controls
- **Document injection pipeline** — `auto_segment`, `inject_document`, and `ResidualVoid.inject`
- **Transparent guest projection mode** — controlled read-only access via `ResidualNetworkManager.guest_project`
- **HTTP service + zero-config discovery** — bundled `--serve` runtime with mDNS and well-known discovery endpoints

### Preserved from v2.0
- Append-only residual locking with cryptographic hash chain
- Dual projection modes (exact / synthesize) with hard refusal gates
- Per-node HMAC signing via `SecureNode`
- Config-file and environment-variable secret resolution
- Full backward-compatible public API

## Migration from v2.0

No breaking import changes. All v2.0 imports continue to work.

```python
# v2.0 imports still work unchanged
from residual_void import ResidualVoid, ResidualNetworkManager, SecureNode
from residual_void import CoherentField, CoherentVoid, Residual
```

`geometry` and `mind` layers previously optional are now loaded automatically.

## Installation

```bash
git clone https://github.com/RaccoonStampede/Residual-Void.git
cd Residual-Void
pip install -e .
```

## Service & Discovery

```bash
residual-void --serve --port 7700
```

- `GET /.well-known/residualvoid.json` and `GET /discover` expose service metadata
- `GET /status` returns runtime status
- `POST /lock`, `POST /project`, and `POST /inject` expose the core runtime actions
- `discover_and_connect()` resolves an mDNS-advertised instance and falls back to `127.0.0.1:7700`

## Validation

The v2.3 build completed with 189 passing tests in the full local suite. Coverage includes
complete WHY/HOW/WHEN-style Synthesize cells, Exact Source isolation, refusal behavior,
multi-item compatibility, Source/Shadow boundaries, and default-off Pure-Harness behavior.

## Security Notes

⚠️ **Critical:** Set a strong secret via `ResidualVoid(secret=...)` or the config file's `security.secret_key` field. Never use the default development secret in production. If using `residual_void_production.py` directly, replace the `SHARED_SECRET` constant with a cryptographically secure random value (e.g., `secrets.token_bytes(32)`).

## Version History

### v2.3.0 — 2026-08-19
- Added complete grounded Synthesize Intent Cells and bounded compatible support assembly
- Preserved Exact Source-only and existing multi-item retrieval boundaries
- Added regression and HTTP smoke coverage for complete WHY/HOW/WHEN-style answers

### v2.2.0 — 2026-08-14
- Added Unified Master parity ranking/synthesize engine features
- Added `PersistentVoid` append-only persistence and fail-closed load checks
- Added snapshot/restore and drift audit
- Added document ingestion and transparent guest projection support

### v2.1.0 — 2026-08-14
- Promoted unified production build as default runtime
- Geometry and mind layers on default import path
- Added `--network-demo` CLI flag
- Updated README, CHANGELOG, pyproject.toml

### v1.0.0 — 2026-08-13
- Initial production release with all core systems restored and verified

## License

MIT License

## Support

- Issues: https://github.com/RaccoonStampede/Residual-Void/issues
- Discussions: https://github.com/RaccoonStampede/Residual-Void/discussions

---

**ResidualVoid v2.3 is production-ready with complete grounded Synthesize Intent Cells and
the unified runtime as default.**
