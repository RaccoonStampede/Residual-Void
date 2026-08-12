# ADR 0001 — Production Baseline

| Field | Value |
|---|---|
| **ID** | 0001 |
| **Title** | Production Baseline for Residual-Void |
| **Status** | Accepted |
| **Date** | 2026-08-12 |
| **Authors** | Engineering team |

---

## Context

Residual-Void is moving from a development scaffold toward a production-capable system.
Several foundational decisions must be locked in before code is deployed to production
environments.  This ADR records those decisions and their rationale.

---

## Decisions

### 1. Environment Detection via `APP_ENV`

**Decision:** Use a single `APP_ENV` environment variable (`development` | `staging` |
`production`) to gate production-specific validation.

**Rationale:** Industry-standard approach; backward compatible (defaults to `development`
when unset); allows staging to mirror production validation without requiring separate code
paths.

**Consequences:** All startup paths must read `APP_ENV` early.  Config loader enforces
production rules only when `APP_ENV=production`.

---

### 2. Fail-Fast on Placeholder Secrets in Production

**Decision:** The config loader will hard-fail at startup if any secret value matches a
known placeholder when `APP_ENV=production`.

**Rationale:** Placeholder secrets in production are a leading cause of security incidents.
A startup failure with a clear error message is far preferable to a running system with
trivially guessable secrets.

**Consequences:** Operators must set real secrets before deploying to production.  CI/CD
pipelines should run `--validate` against the production config profile.

---

### 3. Replay Protection: Timestamp + Nonce + kid + TTL + Skew

**Decision:** All inter-component messages carry `kid`, `iat`, `exp`, and `nonce` claims.
ResidualNetworkManager validates all four before accepting any message.

**Rationale:** Protects against replay attacks in an eventually-consistent distributed
system where message ordering is not guaranteed.

**Parameters:**
- Default TTL: 30 s
- Default clock skew: 10 s
- Nonce cache TTL: `TTL + 2 * skew`

**Consequences:** NTP synchronization is required on all nodes.  Nonce cache must be
sized for peak message volume.

---

### 4. Key Rotation: Active + Previous + Grace Window

**Decision:** The system maintains an active signing key and an optional previous signing
key.  Both are accepted during the configurable grace window (default 300 s).

**Rationale:** Enables zero-downtime key rotation with a rolling deployment.  Simplest
model that avoids a dedicated key-management microservice at this stage.

**Consequences:** Key rotation is a manual procedure (see
[security.md#key-rotation-model](../security.md#key-rotation-model)).  A future ADR
should address integration with a secrets manager.

---

### 5. WAL Mode for Persistence

**Decision:** All database-backed components (ResidualVoid, CoherentVoid) MUST use WAL
mode.

**Rationale:** WAL provides better read/write concurrency, faster crash recovery, and
enables continuous archiving (PITR).

**Consequences:** WAL must be explicitly enabled for SQLite connections.  PostgreSQL is
always WAL-mode; no additional config required.

---

### 6. Snapshot Retention Policy

**Decision:** Keep at most `snapshot_retain_count` (default 10) snapshots.  Snapshots are
written atomically via temp-file + rename.

**Rationale:** Prevents unbounded disk growth.  Atomic writes prevent partial-snapshot
corruption.

**Consequences:** Operators must provision sufficient disk for `retain_count` snapshots.
Snapshot integrity is verified on load; corrupt snapshots trigger fallback to prior.

---

### 7. Non-Breaking Config Defaults

**Decision:** All new config keys must have safe non-production defaults.  No existing
caller interface will be broken by this release.

**Rationale:** Minimizes risk of the documentation/configuration rollout itself causing
incidents.

**Consequences:** Production operators must opt-in to production-mode validation by
setting `APP_ENV=production`.

---

## Alternatives Considered

| Decision | Alternative | Why Rejected |
|---|---|---|
| Fail-fast on placeholder secrets | Warn only | Warnings are ignored; hard failures are not |
| Grace window key rotation | Immediate rotation | Would drop in-flight tokens; downtime risk |
| WAL persistence | No-WAL SQLite | Higher corruption risk on crash |
| `APP_ENV` for environment | Multiple flags | More complex; `APP_ENV` is the de-facto standard |

---

## Related Documents

- [docs/security.md](../security.md)
- [docs/operations.md](../operations.md)
- [docs/configuration.md](../configuration.md)
- [docs/roadmap.md](../roadmap.md)
