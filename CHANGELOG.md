# Changelog

All notable changes to Residual-Void will be documented in this file.

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
