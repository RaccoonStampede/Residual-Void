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

## Retrieval and Optional Dynamics

Public ingestion uses a **HyperSeed Source/Shadow** contract:

```text
public lock
  ├─ immutable complete Source ──> Exact evidence only
  └─ grounded extractive Shadows ─> Synthesize candidates only
                                      │
                                      ▼
                  target → seed → grounding → frame → carrier gates
                                      │
                                      ▼
                       optional bounded Pure-Harness phase tie-breaker
```

The gates and the unmodified primary-answer admission cutoff run before any phase adjustment. The
optional adjustment operates only on candidates that already pass that cutoff; it cannot add a
candidate, convert a Source into a Synthesize candidate, or turn a baseline refusal into an
answer. Source records are excluded from governance and ranking updates, while Shadows retain a
link to their Source.

### Synthesize Intent Cells

After the existing Synthesize eligibility gates succeed, the single-answer path classifies the
query into a structured Intent Cell. The current branches are WHY, WHEN, HOW, WHO, WHAT,
definition, mechanism, diagnosis, and general factual questions.

Intent lineage and topic-family preference are tie-breaking signals only; they run after target
identity, grounding, seed scope, frame, carrier alignment, and the primary-answer admission
floor. This prevents a matching label or lineage from rescuing an off-target or weakly grounded
Shadow.

The formatter emits the complete cleaned body of the admitted primary Shadow. It may include up
to two compatible supporting Shadow bodies when they share the primary topic or Source and an
allowed adjacent intent branch. It does not invent connective prose, labels, paraphrases, or
sentence fragments. A longer locked body remains intact when it is the only suitable evidence.

Exact retrieval exits through its Source-only path before Intent Cell classification and remains
unassembled. LIST, STEPS, COMPARE, RELATE, and SUMMARIZE continue through their existing
multi-item assembly paths.

### Pure-Harness evaluator

`PureHarnessDynamics` is a deterministic, opt-in evaluator for scalar residual response and
multi-pair flow diagnostics. Its scalar law is:

```text
R0 / (1 + gamma) + beta * sin(gamma * n + phase)
```

The evaluator is separate from retrieval by default. It affects Synthesize only when both
`enabled` and `synthesize_phase_signal_enabled` are true. In that mode, the runtime applies raw
centered phase-quality offsets only to multiple admitted candidates inside the configured
tie window, after the normal carrier pass. Offsets are limited to `±0.06` and protected by the
primary-admission floor. Exact retrieval remains Source-only and unchanged.

This feature is a controlled ranking signal, not a claim that any external experimental model is
validated for answer quality. Its purpose is limited to resolving close, already-grounded
Synthesize candidates.

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
