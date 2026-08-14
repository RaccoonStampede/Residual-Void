# Changelog

All notable changes to Residual-Void will be documented in this file.

## [2.2.0] - 2026-08-14

### Added
- Extended `CoherentField` ranking with fuzzy token recovery, phrase anchors/bridges, resonance/frequency scoring, and value bias.
- Added intent-aware synthesize projection flow with query-chain logging and Bellman-style residual value updates.
- Added `PersistentVoid` append-only JSONL persistence runtime with fail-closed load behavior.
- Added snapshot APIs (`snapshot`, `list_snapshots`, `restore`, `save_snapshot_file`, `load_snapshot_file`) and `audit_drift`.
- Added document ingestion helpers: `auto_segment`, `inject_document`, and `ResidualVoid.inject`.
- Added `ResidualNetworkManager` support for `mode="private"|"transparent"` plus `guest_project`.
- Added parity-focused tests for ranking, synthesize quality, persistence, snapshots, drift, ingestion, and transparent guest access.

## [2.1.0] - 2026-08-14

### Changed
- Promoted unified production build as the default runtime (was previously opt-in)
- `geometry.py` (`ResidualGeometry`) and `mind.py` (`ResidualFieldMind`) layers are now loaded on the default import path
- Updated `__init__.py` docstring and `__version__` to reflect v2.1 unified runtime
- Bumped `pyproject.toml` version to `2.1.0` with updated description
- Rewrote `README.md` to document v2.1 unified production build, updated Quick start and API examples
- Added `--network-demo` CLI flag to `__main__.py` for multi-network smoke demo
- Updated `RELEASE.md` with v2.1.0 release notes

### Default runtime now includes
- Hierarchical edge-nulling Pi-Helix extractor (v2)
- Nested geometric shells + Fibonacci placement
- Hierarchical message-passing + Laplacian/Fiedler eigenvalue
- Fast/Medium/Deep imprint layers
- Ghost tax + ethical tilt + god-zone regulation (drift target ≈ 0.008)
- Binary residual path with SHA-256 + Blake2b + HMAC signing
- Unlimited private mergers via `ResidualNetworkManager`

### Migration from v2.0
- No breaking import changes; all v2.0 imports continue to work
- `geometry` and `mind` layers previously optional are now loaded automatically if available
- `SecureNode` constructor expects a `CoherentVoid` instance (pass `void._void`), unchanged from v2.0

## [2.0.0] - 2026-08-13

### Changed
- Simplified default path to lean permanent core with cryptographic hash chain
- Geometry/mind/Pi-Helix layers moved to optional/experimental (not loaded by default)
- `pyproject.toml` version bumped to `2.0.0`

### Added
- Append-only residual locking with SHA-256 hash chain (`prev_hash` → `chain_hash`)
- Dual projection modes (`exact`, `synthesize`) with hard refusal gates
- Packed 32-byte signatures for efficient matching and ranking
- `ResidualNetworkManager` with isolated secrets, key rotation, nonce replay protection

## [0.1.0] - 2026-08-12

### Added
- Python package metadata for installable builds
- CLI entry point and version flag
- CI workflow for automated validation
- project license and release-focused documentation polish
- basic runtime smoke validation for the built package
- signed-envelope nonce and replay-protection validation for release-grade security checks
- config validation coverage for production placeholder secret rejection and environment overrides

### Changed
- Normalized the project into a package-install workflow
- Added explicit pytest dependency for clean development environments
- Marked the repository status as release candidate based on validated build and test evidence

### Fixed
- Missing build metadata that prevented `pip install .`
- Missing dev/test dependency that blocked local pytest usage
- Missing nonce/timing claims in signed payloads required for replay protection
- Missing message validation path for duplicate nonce rejection and rotated-key acceptance

## [Unreleased]

### Planned
- extended persistence validation coverage
- runtime security and deployment hardening beyond the current release candidate baseline
- packaging and release automation improvements
