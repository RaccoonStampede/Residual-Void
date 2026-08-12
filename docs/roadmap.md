# Roadmap

> Cross-references: [architecture.md](architecture.md) · [test-traceability.md](test-traceability.md) · [adr/0001-production-baseline.md](adr/0001-production-baseline.md)

---

## Current State (Baseline)

The repository contains the foundational documentation and configuration scaffolding.
No production runtime code has been deployed.  The config loader is implemented with
non-breaking defaults.

---

## Engineering Phases

### Phase 1 — Production Safety Foundation (Immediate)

**Goal:** Establish non-negotiable safety controls before any production deployment.

| Task | Owner | Priority | Notes |
|---|---|---|---|
| Implement `tests/test_config_loader.py` | Engineering | P0 | See [test-traceability.md](test-traceability.md) |
| Wire `APP_ENV` detection into all startup paths | Engineering | P0 | Non-breaking: defaults to `development` |
| Implement nonce cache (in-memory LRU) | Engineering | P0 | Prerequisite for replay protection |
| Implement token validation in ResidualNetworkManager | Engineering | P0 | Replay + expiry + skew |
| Provision mTLS certificates for staging | DevOps | P0 | Required before staging traffic |
| Set up NTP on all cluster nodes | DevOps | P0 | Required for skew handling |

### Phase 2 — Persistence Hardening (Near-term)

**Goal:** Make persistence production-safe with WAL, snapshots, and recovery.

| Task | Owner | Priority | Notes |
|---|---|---|---|
| Enable WAL mode in SQLite path | Engineering | P1 | See [operations.md#wal-configuration](operations.md#wal-configuration) |
| Implement atomic snapshot writes | Engineering | P1 | Temp-file + rename pattern |
| Implement snapshot integrity check on startup | Engineering | P1 | Hash-verify before loading |
| Implement snapshot pruning | Engineering | P1 | Configurable retain count |
| Add WAL archiving for PostgreSQL path | DevOps | P1 | Required for PITR |
| Implement `tests/test_persistence.py` | Engineering | P1 | |

### Phase 3 — Key Rotation & Secret Management (Near-term)

**Goal:** Enable zero-downtime secret and key rotation.

| Task | Owner | Priority | Notes |
|---|---|---|---|
| Implement key rotation grace window in token validation | Engineering | P1 | See [security.md#key-rotation-model](security.md#key-rotation-model) |
| Integrate with secrets manager (Vault / AWS SM / etc.) | Engineering | P2 | Avoids YAML-based secret storage |
| Implement `tests/test_security.py` | Engineering | P1 | Covers rotation + replay |
| Document key rotation runbook in [operations.md](operations.md) | Engineering | P1 | Already drafted; validate against impl |

### Phase 4 — Observability (Medium-term)

**Goal:** Achieve full production visibility.

| Task | Owner | Priority | Notes |
|---|---|---|---|
| Instrument ResidualVoid with Prometheus metrics | Engineering | P2 | See metrics table in [operations.md](operations.md) |
| Instrument CoherentVoid epoch transitions | Engineering | P2 | |
| Implement `/healthz` and `/readyz` endpoints | Engineering | P2 | Required for orchestrator health checks |
| Set up centralized log aggregation | DevOps | P2 | |
| Create alerting rules from [operations.md#monitoring](operations.md#monitoring) | DevOps | P2 | |

### Phase 5 — Cluster Hardening (Medium-term)

**Goal:** Harden multi-node operation.

| Task | Owner | Priority | Notes |
|---|---|---|---|
| Implement ResidualNetworkManager peer authentication | Engineering | P1 | mTLS + signed envelopes |
| Implement CoherentVoid quorum enforcement | Engineering | P1 | Halt on < quorum_size peers |
| Implement blocked_peers enforcement | Engineering | P2 | |
| Load test 3-node cluster | Engineering | P2 | Baseline capacity numbers |
| Document network topology requirements | Engineering | P2 | Already drafted in architecture.md |

### Phase 6 — Full Production GA (Long-term)

- All Phase 1–5 tasks complete.
- External penetration test completed and findings remediated.
- Runbook validated in staging game day.
- SLA / SLO defined and measured.
- Disaster recovery drill completed.

---

## Recommended Task Sequencing

```
P0 tasks (Phase 1) must all complete before any production traffic.

Phase 1 → Phase 2 + Phase 3 (can run in parallel)
        → Phase 4 (can start in parallel with Phase 2/3)

Phase 2 + Phase 3 → Phase 5
Phase 4 + Phase 5 → Phase 6 (GA)
```

---

## Assumptions and Decisions

See [docs/adr/0001-production-baseline.md](adr/0001-production-baseline.md) for the
architectural decisions underlying this roadmap.
