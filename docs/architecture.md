# Architecture

> Cross-references: [security.md](security.md) · [operations.md](operations.md) · [configuration.md](configuration.md)

---

## Overview

Residual-Void is a distributed coherence engine. It manages a shared **residual field** — a
probabilistic state space that converges across nodes — using four collaborating components.

```
┌─────────────────────────────────────────────────────────┐
│                        Cluster                          │
│                                                         │
│  ┌──────────────────┐     ┌──────────────────────────┐  │
│  │  ResidualVoid    │────▶│  CoherentVoid            │  │
│  │  (core engine)   │◀────│  (consensus / coherence) │  │
│  └────────┬─────────┘     └──────────────────────────┘  │
│           │                          ▲                   │
│           ▼                          │                   │
│  ┌──────────────────┐     ┌──────────┴───────────────┐  │
│  │ ResidualFieldMind│────▶│ ResidualNetworkManager   │  │
│  │  (inference)     │     │  (routing / discovery)   │  │
│  └──────────────────┘     └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Components

### ResidualVoid (Core Engine)

- **Responsibility:** Maintains the primary residual-field accumulator. Accepts field
  contributions from peers, applies decay and normalization, and exposes the current
  coherence boundary to other components.
- **State:** Persistent. Uses WAL-backed storage (see [operations.md](operations.md)).
- **Interfaces:** Internal gRPC/message bus; does not expose public HTTP.
- **Failure mode:** On loss of quorum the component halts accumulation and signals
  `DEGRADED` to CoherentVoid.

### CoherentVoid (Consensus / Coherence Layer)

- **Responsibility:** Propagates coherence-state changes across the cluster.  Mediates
  conflicts between competing residual-field contributions.  Drives epoch transitions.
- **State:** Derived from ResidualVoid; ephemeral coherence metadata is checkpointed.
- **Interfaces:** Bidirectional with ResidualVoid; publishes epoch-change events to
  ResidualFieldMind.

### ResidualFieldMind (Inference Engine)

- **Responsibility:** Runs inference passes over the current residual field.  Produces
  action recommendations and policy updates consumed by ResidualVoid.
- **State:** Stateless per inference pass; persists model artifacts separately.
- **Interfaces:** Subscribes to CoherentVoid epoch events; writes policy updates back to
  ResidualVoid.

### ResidualNetworkManager (Network / Routing)

- **Responsibility:** Manages peer discovery, connection health, and message routing.
  Provides authenticated transport between all other components.
- **State:** Routing table (in-memory, rebuilt on restart from seed peers).
- **Interfaces:** All inter-component messages pass through ResidualNetworkManager;
  applies signing and replay-protection envelopes (see [security.md](security.md)).

---

## Data Flow

```
External Input
     │
     ▼
ResidualNetworkManager (authenticate, replay-check, route)
     │
     ▼
ResidualVoid (accumulate field contribution)
     │
     ├──▶ CoherentVoid (consensus check, epoch management)
     │         │
     │         └──▶ ResidualFieldMind (inference → policy)
     │                   │
     └─────────────────◀─┘ (policy update feedback)
```

---

## Persistence Contract

| Component | Storage | Mode | Notes |
|---|---|---|---|
| ResidualVoid | SQLite / PostgreSQL | WAL | Primary residual-field state |
| CoherentVoid | SQLite / PostgreSQL | WAL | Epoch metadata + coherence checkpoints |
| ResidualFieldMind | File system | Append-only | Model artifact blobs |
| ResidualNetworkManager | In-memory | — | Rebuilt from seed config on restart |

Full persistence and recovery semantics: [operations.md#persistence](operations.md#persistence).

---

## Deployment Topology

```
                ┌──── Node A ────┐    ┌──── Node B ────┐
                │  ResidualVoid  │    │  ResidualVoid  │
                │  CoherentVoid  │◀──▶│  CoherentVoid  │
                │  FieldMind     │    │  FieldMind     │
                │  NetworkMgr    │    │  NetworkMgr    │
                └────────────────┘    └────────────────┘
                         ▲                    ▲
                         └────────────────────┘
                              Mesh (mTLS)
```

- Minimum production cluster: **3 nodes** (quorum = 2).
- Network transport is mutually authenticated (mTLS or equivalent).
- Clock synchronization (NTP/PTP) is required for replay-protection skew handling.

---

## Configuration Surface

All runtime-configurable knobs are documented in [configuration.md](configuration.md).
The example config is at `config/residualvoid.example.yaml`.
