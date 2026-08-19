# Configuration Reference

> Cross-references: [architecture.md](architecture.md) · [security.md](security.md) · [operations.md](operations.md)

---

## Overview

Residual-Void is configured through a YAML file copied from the repository example:
`config/residualvoid.example.yaml` to `config/residualvoid.yaml`, combined with
environment-variable overrides. Environment variables always take precedence over file values.

This repo does not ship a ready-to-use production config at `config/residualvoid.yaml`; create
that file locally from the example before validation or deployment.

---

## Environment Detection

| Variable | Values | Default |
|---|---|---|
| `APP_ENV` | `development`, `staging`, `production` | `development` |

When `APP_ENV=production`, the config loader applies strict validation:
- Rejects placeholder/default secret values (fail-fast).
- Requires minimum secret entropy.
- Requires explicit DB URL.

---

## Config Matrix

### Top-level Structure

```yaml
environment: development          # overridden by APP_ENV env var
node_id: ""                       # required; unique per node
log_level: info

security: { ... }
network: { ... }
coherence: { ... }
persistence: { ... }
fieldmind: { ... }
```

---

## Synthesize Intent Cell Behavior

Intent Cells do not add a configuration surface. They are the default single-answer
Synthesize assembly contract:

| Query family | Primary branch | Compatible support examples |
|---|---|---|
| `why` / causal WHAT | `why` | `mechanism` |
| `when` / timing | `when` | `condition` |
| `how` / process | `how` | `mechanism` |
| `who` / entity | `who` | `what`, `fact` |
| `what is` / `define` | `definition` | `what` |
| failure or troubleshooting | `diagnose` | `why`, `mechanism`, `condition` |
| explicit mechanism | `mechanism` | `how`, `process` |
| conditional `what happens` | `what` | `condition`, `effect` |
| other `what` questions | `what` | `mechanism` |
| non-interrogative fallback | `general` | none |

All normal relevance, target, grounding, seed, frame, carrier, and primary-admission
gates run before lineage/topic preference. The output contains the complete locked Shadow
body and may include no more than two compatible supporting bodies. No truncation,
paraphrase, or generated connective label is used.

This behavior does not affect Exact retrieval, which remains Source-only and unassembled,
or the existing multi-item Synthesize paths.

---

## Pure-Harness Runtime Controls

Pure-Harness controls are configured programmatically on a running `ResidualVoid`; they are not
loaded from the YAML/environment configuration surface above.

```python
from residual_void import ResidualVoid

runtime = ResidualVoid()
runtime.configure_pure_harness(
    enabled=True,
    synthesize_phase_signal_enabled=True,
    synthesize_phase_signal_max_bonus=0.06,
    synthesize_phase_signal_tie_window=0.06,
)
```

| Option | Default | Valid values | Purpose |
|---|---:|---|---|
| `enabled` | `False` | Boolean | Enables Pure-Harness evaluation and multi-pair diagnostics. |
| `synthesize_phase_signal_enabled` | `False` | Boolean | Allows the optional Synthesize phase tie-breaker; requires `enabled=True`. |
| `synthesize_phase_signal_max_bonus` | `0.06` | finite number in `(0, 0.06]` | Absolute cap for each raw, centered Synthesize phase offset. |
| `synthesize_phase_signal_tie_window` | `0.06` | finite number in `(0, 0.25]` | Maximum baseline score gap for invoking the phase tie-breaker. |
| `default_ghost_tax_floor` | `0.05` | finite number | Soft floor used by multi-pair flow diagnostics. |
| `max_oscillation_amplitude` | `0.01` | finite positive number | Maximum permitted sinusoidal correction amplitude. |

The status surface exposes the effective configuration:

```python
status = runtime.status()["void"]["pure_harness"]
assert status["coupled_to_retrieval"] is False  # default
```

`coupled_to_retrieval` becomes true only when both enablement flags are true. The phase signal
runs only when at least two candidates remain within the configured tie window, after the normal
target, seed, grounding, frame, carrier, and unmodified primary-admission gates. It cannot
introduce an ineligible candidate, turn a baseline refusal into an answer, or affect Exact retrieval.

Runtime tuning is held in process memory. Reapply these settings after a restart if you choose to
use them; no persistence behavior is implied by this API.

---

### `security`

| Key | Env var override | Required in prod | Default | Description |
|---|---|---|---|---|
| `secret_key` | `RESIDUALVOID_SECRET_KEY` | **Yes** | — | HMAC master secret (≥ 32 chars) |
| `signing_key` | `RESIDUALVOID_SIGNING_KEY` | **Yes** | — | Active JWT/message signing key |
| `previous_signing_key` | `RESIDUALVOID_PREVIOUS_SIGNING_KEY` | No | `""` | Previous key (grace window only) |
| `key_rotation_grace_seconds` | — | No | `300` | Grace window duration (seconds) |
| `token_ttl_seconds` | — | No | `30` | Token TTL for replay protection |
| `max_clock_skew_seconds` | — | No | `10` | Max accepted clock skew |
| `nonce_cache_backend` | — | No | `memory` | `memory` or `redis` |
| `nonce_cache_redis_url` | `RESIDUALVOID_NONCE_REDIS_URL` | Cond. | — | Required if `nonce_cache_backend=redis` |

> ⚠️ **Production:** `secret_key` and `signing_key` must not match any placeholder value.
> The config loader will refuse to start if they do.

Placeholder values that are rejected in production:
`CHANGE_ME`, `changeme`, `placeholder`, `secret`, `todo`, `xxx`, `your-secret`, `default`

---

### `network`

| Key | Env var override | Required in prod | Default | Description |
|---|---|---|---|---|
| `listen_address` | — | No | `0.0.0.0` | Bind address for ResidualNetworkManager |
| `listen_port` | — | No | `7700` | Bind port |
| `seed_peers` | — | **Yes** | `[]` | Bootstrap peer list (`host:port`) |
| `tls_cert_file` | — | **Yes** (mTLS) | — | Path to TLS certificate |
| `tls_key_file` | — | **Yes** (mTLS) | — | Path to TLS private key |
| `tls_ca_file` | — | **Yes** (mTLS) | — | Path to CA bundle for peer verification |
| `blocked_peers` | — | No | `[]` | Peers to unconditionally reject |
| `connection_timeout_seconds` | — | No | `5` | Dial timeout |

---

### `coherence`

| Key | Required in prod | Default | Description |
|---|---|---|---|
| `quorum_size` | **Yes** | `2` | Minimum nodes for consensus |
| `epoch_timeout_seconds` | No | `60` | Max seconds before epoch failure |
| `heartbeat_interval_seconds` | No | `5` | CoherentVoid heartbeat frequency |

---

### `persistence`

| Key | Env var override | Required in prod | Default | Description |
|---|---|---|---|---|
| `db_url` | `RESIDUALVOID_DB_URL` | **Yes** | `sqlite:///./data/residualvoid.db` | Database connection string |
| `snapshot_dir` | — | No | `./data/snapshots/` | Snapshot storage directory |
| `snapshot_interval_seconds` | — | No | `300` | How often snapshots are taken |
| `snapshot_retain_count` | — | No | `10` | Number of snapshots to keep |
| `snapshot_restore_path` | — | No | `""` | Force restore from specific snapshot |
| `wal_checkpoint_interval` | — | No | `1000` | SQLite WAL checkpoint page count |

---

### `fieldmind`

| Key | Required in prod | Default | Description |
|---|---|---|---|
| `model_artifact_dir` | No | `./data/models/` | Path to ResidualFieldMind model blobs |
| `inference_timeout_seconds` | No | `10` | Max inference pass duration |
| `policy_update_interval_seconds` | No | `30` | How often policies are pushed to ResidualVoid |

---

## Environment Variable Overrides (Summary)

| Variable | Config key |
|---|---|
| `APP_ENV` | `environment` |
| `RESIDUALVOID_NODE_ID` | `node_id` |
| `RESIDUALVOID_SECRET_KEY` | `security.secret_key` |
| `RESIDUALVOID_SIGNING_KEY` | `security.signing_key` |
| `RESIDUALVOID_PREVIOUS_SIGNING_KEY` | `security.previous_signing_key` |
| `RESIDUALVOID_DB_URL` | `persistence.db_url` |
| `RESIDUALVOID_NONCE_REDIS_URL` | `security.nonce_cache_redis_url` |

---

## Migration Guide

### From: No explicit environment concept

If your deployment does not set `APP_ENV`, the system defaults to `development`.
No behavior change. To move toward production:

1. Copy `config/residualvoid.example.yaml` to `config/residualvoid.yaml`.
2. Set `APP_ENV=production` in your deployment environment.
3. Ensure all secrets are set via environment variables (not YAML literals).
4. Run `python src/config_loader.py --validate config/residualvoid.yaml` — it will report
   any placeholder values that must be replaced.

### From: SQLite to PostgreSQL

1. Provision PostgreSQL instance with WAL archiving.
2. Set `RESIDUALVOID_DB_URL=******host/dbname`.
3. Run database migrations.
4. Restart components; they will use PostgreSQL on next boot.
5. Decommission SQLite file after confirming stability.

### From: No mTLS

1. Generate CA, server, and client certificates.
2. Set `network.tls_cert_file`, `network.tls_key_file`, `network.tls_ca_file` in config.
3. Deploy certificates to all nodes.
4. Restart ResidualNetworkManager on each node.
5. Verify `/healthz` on all nodes after restart.
