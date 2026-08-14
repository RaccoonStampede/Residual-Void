# ResidualVoid v2.2.0 – Unified Production Runtime

**Release Date:** 2026-08-14
**Status:** Production Ready ✅

## Overview

ResidualVoid v2.2 promotes parity with Unified Master ranking/synthesis and persistence features while keeping the modular package API.
All advanced capabilities previously delivered in `residual_void_production.py` are now
the package default, accessible via `pip install .` and `from residual_void import ...`.

## What's Included

### Default Runtime (v2.2)
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
- **Persistent append-only runtime** — `PersistentVoid` JSONL chain support
- **Snapshot / restore / drift audit** — reproducibility and stability controls
- **Document injection pipeline** — `auto_segment`, `inject_document`, and `ResidualVoid.inject`
- **Transparent guest projection mode** — controlled read-only access via `ResidualNetworkManager.guest_project`

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

## Security Notes

⚠️ **Critical:** Set a strong secret via `ResidualVoid(secret=...)` or the config file's `security.secret_key` field. Never use the default development secret in production. If using `residual_void_production.py` directly, replace the `SHARED_SECRET` constant with a cryptographically secure random value (e.g., `secrets.token_bytes(32)`).

## Version History

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

**ResidualVoid v2.1 is production-ready with unified runtime as default.** 🚀
