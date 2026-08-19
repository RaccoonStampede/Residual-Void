# Test Traceability Matrix

> Cross-references: [architecture.md](architecture.md) · [security.md](security.md) · [roadmap.md](roadmap.md)

This document maps production-readiness requirements to test coverage.  
`[FUTURE]` indicates a test that does not yet exist and is planned.

---

## Requirements → Test Coverage

### REQ-SEC-01: Placeholder secrets rejected in production

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_config_loader.py::test_placeholder_secret_rejected_in_production` | Config loader raises error for `CHANGE_ME` secret when `APP_ENV=production` | `tests/test_config_loader.py` | [FUTURE] |
| `test_config_loader.py::test_all_known_placeholders_rejected` | All known placeholder strings are rejected | `tests/test_config_loader.py` | [FUTURE] |
| `test_config_loader.py::test_placeholder_allowed_in_development` | Placeholder accepted silently in `development` env | `tests/test_config_loader.py` | [FUTURE] |

### REQ-SEC-02: Replay protection — nonce + timestamp + TTL

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_security.py::test_valid_token_accepted` | Token within TTL and skew accepted | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_expired_token_rejected` | Token past `exp + skew` rejected | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_future_token_rejected` | Token with `iat` > `now + skew` rejected | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_duplicate_nonce_rejected` | Second use of same nonce rejected | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_nonce_accepted_after_cache_expiry` | Nonce accepted after cache TTL window | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_skew_window_boundary` | Token at exact skew boundary accepted/rejected | `tests/test_security.py` | [FUTURE] |

### REQ-SEC-03: Key rotation — active + previous + grace window

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_security.py::test_token_signed_with_active_key_accepted` | Token signed with active key accepted | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_token_signed_with_previous_key_accepted_in_grace` | Token signed with previous key accepted during grace window | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_token_signed_with_previous_key_rejected_after_grace` | Token signed with previous key rejected after grace window | `tests/test_security.py` | [FUTURE] |
| `test_security.py::test_unknown_kid_rejected` | Token with unknown `kid` rejected | `tests/test_security.py` | [FUTURE] |

### REQ-CONFIG-01: Config loader — environment detection

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_config_loader.py::test_default_environment_is_development` | Default env is `development` when `APP_ENV` not set | `tests/test_config_loader.py` | [FUTURE] |
| `test_config_loader.py::test_app_env_overrides_file` | `APP_ENV` env var overrides YAML value | `tests/test_config_loader.py` | [FUTURE] |
| `test_config_loader.py::test_env_var_overrides_yaml_secret` | `RESIDUALVOID_SECRET_KEY` env var overrides YAML | `tests/test_config_loader.py` | [FUTURE] |

### REQ-CONFIG-02: Config loader — minimum entropy validation

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_config_loader.py::test_short_secret_rejected_in_production` | Secret < 32 chars rejected in production | `tests/test_config_loader.py` | [FUTURE] |
| `test_config_loader.py::test_sufficient_secret_accepted` | Secret ≥ 32 chars accepted | `tests/test_config_loader.py` | [FUTURE] |

### REQ-PERSIST-01: WAL mode and snapshot integrity

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_persistence.py::test_wal_mode_enabled` | SQLite connection uses WAL journal mode | `tests/test_persistence.py` | [FUTURE] |
| `test_persistence.py::test_snapshot_written_atomically` | Snapshot write uses temp-file + rename | `tests/test_persistence.py` | [FUTURE] |
| `test_persistence.py::test_corrupt_snapshot_falls_back_to_previous` | Corrupt latest snapshot causes fallback | `tests/test_persistence.py` | [FUTURE] |
| `test_persistence.py::test_snapshot_pruning` | Old snapshots pruned to retain count | `tests/test_persistence.py` | [FUTURE] |

### REQ-ARCH-01: Component initialization

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_residualvoid.py::test_residualvoid_starts_with_valid_config` | ResidualVoid initializes with valid config | `tests/test_residualvoid.py` | [FUTURE] |
| `test_coherentvoid.py::test_coherentvoid_epoch_advance` | CoherentVoid advances epoch on quorum | `tests/test_coherentvoid.py` | [FUTURE] |
| `test_fieldmind.py::test_fieldmind_inference_returns_policy` | ResidualFieldMind inference produces policy | `tests/test_fieldmind.py` | [FUTURE] |
| `test_networkmanager.py::test_networkmanager_routes_message` | ResidualNetworkManager routes message to target | `tests/test_networkmanager.py` | [FUTURE] |

---

### REQ-RETRIEVAL-01: Source/Shadow retrieval boundaries

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_hyperseed_source_shadow.py` | Public locks create grounded Source/Shadow pairs; Exact remains Source-only and Synthesize remains Shadow-only | `tests/test_hyperseed_source_shadow.py` | Covered |
| `test_hyperseed_source_shadow.py` | Source/Shadow metadata survives persistence, HTTP, restore, and rollback paths | `tests/test_hyperseed_source_shadow.py` | Covered |

### REQ-RETRIEVAL-02: Complete Synthesize Intent Cells

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_synthesize_intent_cells.py` | Classifies WHY, WHEN, HOW, WHO, WHAT, definition, mechanism, diagnosis, and general questions into compatible branches | `tests/test_synthesize_intent_cells.py` | Covered |
| `test_synthesize_intent_cells.py` | Returns complete grounded Shadow bodies for WHY, WHEN, HOW, WHO, WHAT, definition, and diagnosis queries | `tests/test_synthesize_intent_cells.py` | Covered |
| `test_synthesize_intent_cells.py` | Limits a cell to one primary plus at most two compatible supports without generated labels or truncation | `tests/test_synthesize_intent_cells.py` | Covered |
| `test_synthesize_intent_cells.py` | Preserves refusal behavior and proves Exact does not enter Synthesize-only Intent Cell helpers | `tests/test_synthesize_intent_cells.py` | Covered |

### REQ-DYN-01: Pure-Harness isolation and bounded phase signal

| Test ID | Description | Location | Status |
|---|---|---|---|
| `test_pure_harness_dynamics.py` | Validates scalar response, modular boundaries, deterministic flow, validation, and default retrieval neutrality | `tests/test_pure_harness_dynamics.py` | Covered |
| `test_pure_harness_dynamics.py::test_phase_signal_is_explicit_and_bounded_after_carrier_alignment` | Confirms explicit enablement and the `±0.06` adjustment cap | `tests/test_pure_harness_dynamics.py` | Covered |
| `test_pure_harness_dynamics.py::test_phase_signal_changes_live_eligible_tie_without_bypassing_gates` | Confirms the enabled post-gate signal affects an eligible tie but cannot answer an unrelated query | `tests/test_pure_harness_dynamics.py` | Covered |
| `test_pure_harness_synthesize_benchmark.py` | Compares baseline and enabled Synthesize results on labeled core, refusal, and same-topic cases | `tests/test_pure_harness_synthesize_benchmark.py` | Covered |

---

## Coverage Gaps Summary

| Area | Gap | Priority |
|---|---|---|
| Security | Replay protection tests | High |
| Security | Key rotation tests | High |
| Config | Placeholder rejection | High |
| Persistence | WAL + snapshot tests | Medium |
| Platform config/cluster docs | Some requirements are documented ahead of implementation | Medium |

---

## Recommended Next Steps

1. Create `tests/` directory with `conftest.py` and shared fixtures.
2. Implement `tests/test_config_loader.py` first (highest risk/value ratio).
3. Implement `tests/test_security.py` second (covers replay + key rotation).
4. Implement `tests/test_persistence.py` third.
5. Implement component-level tests last (requires more infrastructure).
