# ResidualVoid v2.3 — Unified Production Runtime

ResidualVoid v2.3 ships the **unified production build** as its default runtime, now with
built-in HTTP serving and zero-config discovery, combining
hierarchical edge-nulling Pi-Helix extraction, nested geometric shells, Fibonacci placement,
hierarchical message-passing (Laplacian/Fiedler), fast/medium/deep imprint layers,
ghost tax / ethical tilt / god-zone regulation, binary residual path, and unlimited
private mergers through `ResidualNetworkManager`.

---

## What's new in v2.3

- ✅ **Unified production build** is now the default (previously opt-in)
- ✅ **Hierarchical edge-nulling Pi-Helix** extractor active on default path
- ✅ **Nested geometric shells + Fibonacci placement** included
- ✅ **Hierarchical message-passing** (Laplacian spectrum / Fiedler eigenvalue)
- ✅ **Fast / Medium / Deep imprint layers** with multi-pass coherence refinement
- ✅ **Ghost tax + ethical tilt + god-zone regulation** (drift target ≈ 0.008)
- ✅ **Binary residual path** with cryptographic signing (SHA-256 + Blake2b + HMAC)
- ✅ **Unlimited private mergers** via `ResidualNetworkManager`
- ✅ Geometry (`ResidualGeometry`) and mind (`ResidualFieldMind`) layers available on default path
- ✅ All v2.0 security guarantees preserved (HMAC signatures, hash chain, replay protection)
- ✅ Master-parity synthesize ranking (intent + fuzzy + resonance + value bias)
- ✅ HyperSeed Source/Shadow retrieval contract with grounded Synthesize output
- ✅ Complete Synthesize Intent Cells for WHY, WHEN, HOW, WHO, WHAT, definition,
  mechanism, diagnosis, and general questions
- ✅ Sentence-safe extractive answers: one primary Shadow plus up to two compatible
  supporting Shadows, without invented connective prose or mid-sentence truncation
- ✅ Optional Pure-Harness dynamics and a bounded, opt-in phase tie-breaker
- ✅ Persistent append-only JSONL runtime via `PersistentVoid`
- ✅ Snapshot/restore + drift audit APIs
- ✅ Document ingestion helpers (`auto_segment`, `inject_document`, `ResidualVoid.inject`)
- ✅ Transparent network guest projection (`guest_project`)
- ✅ Built-in HTTP service with `--serve` plus mDNS / well-known discovery helpers

---

## Installation

```bash
git clone https://github.com/RaccoonStampede/Residual-Void.git
cd Residual-Void
pip install -r requirements.txt
pip install -e .
```

---

## Quick start (single node)

```python
from residual_void import ResidualVoid, SecureNode

# Use a strong secret in production
void = ResidualVoid(secret="replace-with-strong-secret")
node = SecureNode("machine_A", void._void)

# Lock a residual
print(node.lock_text("CMD::ALERT::AUTHORIZED", domain="command"))

# Project grounded output
print(node.project("CMD::ALERT", mode="exact"))
print(node.project("authorized command", mode="synthesize"))

# Verify chain integrity and check status
print(void.verify_integrity())
print(void.status())
```

---

## Retrieval contract: Sources and Shadows

Public locks create an immutable, complete **Source** plus one or more grounded **Shadows**:

- `mode="exact"` retrieves Source evidence only.
- `mode="synthesize"` retrieves eligible Shadows only, after target, frame, seed, grounding,
  and carrier checks.
- Shadows must remain extractive from their Source; a Source is never changed by governance
  or ranking updates.
- Direct low-level `CoherentField.store()` use remains supported as a legacy path, but public
  locks should use the Source/Shadow model.

This separation prevents a ranking or dynamics signal from turning partial or unrelated text
into evidence. If no grounded candidate survives the relevant gates, the runtime refuses rather
than guessing.

---

## Synthesize Intent Cells

Single-answer Synthesize queries are returned as complete, grounded **Intent Cells**:

- **Primary branches:** WHY, WHEN, HOW, WHO, WHAT, definition, mechanism, diagnosis,
  and general factual queries.
- **Evidence order:** relevance, target identity, grounding, seed scope, frame, carrier
  alignment, and primary-answer admission are evaluated before intent lineage and topic-family
  preference.
- **Assembly:** the primary answer is the complete locked Shadow body. When compatible
  evidence exists, up to two same-topic or same-Source supporting Shadow bodies may be included.
- **Extractive guarantee:** bodies are cleaned from their stored envelopes but are never
  paraphrased, shortened mid-sentence, or joined with generated labels such as `Related:`.

Exact retrieval remains Source-only and unassembled. LIST, STEPS, COMPARE, RELATE, and
SUMMARIZE queries retain their existing multi-item behavior. Unsupported or off-target queries
still refuse instead of falling back to weak token overlap.

---

## Pure-Harness dynamics and optional phase signal

The Pure-Harness evaluator exposes a deterministic residual response:

```text
R0 / (1 + gamma) + beta * sin(gamma * n + phase)
```

It includes named linear-response and modular-window controls, plus optional deterministic
multi-pair flow diagnostics. These controls are **off by default** and do not validate external
experimental claims.

Synthesize already uses its own carrier alignment mechanism. A Pure-Harness signal can be enabled
only as a small, post-gate tie-breaker for candidates that are already eligible:

```python
from residual_void import ResidualVoid

void = ResidualVoid()
void.configure_pure_harness(
    enabled=True,
    synthesize_phase_signal_enabled=True,
    synthesize_phase_signal_max_bonus=0.06,  # valid range: (0, 0.06]
    synthesize_phase_signal_tie_window=0.06,  # only close admitted scores
)

print(void.status()["void"]["pure_harness"])
```

Raw phase offsets are centered only across close candidates that already meet the unmodified
primary-answer cutoff and capped at `±0.06`; an admission floor prevents a negative offset from
creating a new refusal. The signal cannot introduce a candidate, turn a baseline refusal into an
answer, bypass grounding/target/frame/seed checks, change Exact retrieval, or replace the normal
carrier signal. Keep it disabled unless a labeled corpus demonstrates a useful improvement for
your workload.

See [configuration.md](docs/configuration.md#pure-harness-runtime-controls) and
[architecture.md](docs/architecture.md#retrieval-and-optional-dynamics) for details.

---

## Multi-network example via ResidualNetworkManager

```python
from residual_void import ResidualNetworkManager

mgr = ResidualNetworkManager()

net1 = mgr.create_network("line_a", secret="secret-a", initial_nodes=["node_1"])
net2 = mgr.create_network("line_b", secret="secret-b", initial_nodes=["node_2"])

# Lock on line_a
node = mgr.get_node("line_a", "node_1")
node.lock_text("NETWORK::PAYLOAD::OK", domain="general")

print(mgr.list_networks())
print(mgr.network_status("line_a"))
```

---

## CLI

```bash
# Print runtime status
residual-void

# Single-node smoke demo (lock + project)
residual-void --demo

# Multi-network smoke demo
residual-void --network-demo

# Serve ResidualVoid over HTTP with mDNS discovery enabled
residual-void --serve --host 0.0.0.0 --port 7700 --service-name ResidualVoid

# Show version
residual-void --version
```

---

## HTTP service + discovery

Run the bundled service:

```bash
residual-void --serve --port 7700
```

Available endpoints:

- `GET /status`
- `GET /discover`
- `GET /.well-known/residualvoid.json`
- `POST /lock`
- `POST /project`
- `POST /inject`

Python discovery helper:

```python
from residual_void import discover_and_connect

info = discover_and_connect()
print(info["base_url"])
```

---

## Security / auth notes

- All residuals are HMAC-SHA256 signed and Blake2b hashed for deduplication.
- Each `SecureNode` enforces per-node authenticated lock/project operations.
- Nonce + time-window replay protection is active on the network manager path.
- **Set a strong secret via the `ResidualVoid(secret=...)` constructor or your config file's `security.secret_key` field. Never use the default development secret in production.**
- Use long, high-entropy secrets. Rotate secrets regularly.
- Isolate secrets per environment / tenant / network.
- If using `residual_void_production.py` directly, replace the `SHARED_SECRET` constant before deploying.

---

## Public API

```python
from residual_void import (
    ResidualVoid,
    ResidualNetworkManager,
    PersistentVoid,
    SecureNode,
    CoherentField,
    CoherentVoid,
    Residual,
    PureHarnessConfig,
    PureHarnessDynamics,
    ResidualFlowResult,
)
```

Optional geometry / mind layers are also importable:

```python
from residual_void import ResidualGeometry, ResidualFieldMind
```

Service helpers are also available:

```python
from residual_void import create_http_server, serve_residual_void, discover_and_connect
```

---

## Validation

Run the full test suite:

```bash
pytest -q
```

The suite includes Source/Shadow persistence and retrieval coverage, complete Intent Cell
coverage, Pure-Harness scalar and multi-pair dynamics coverage, a labeled
baseline-versus-enabled Synthesize benchmark, and Exact-boundary regression checks.
The v2.3 build completed with 189 passing tests in the full local suite.

Minimal smoke snippet:

```python
from residual_void import ResidualVoid, SecureNode

void = ResidualVoid(secret="test-secret-32-bytes-minimum-please!!")
node = SecureNode("smoke", void._void)

assert node.lock_text("SMOKE::LOCK::OK", domain="test") == "locked"
print(node.project("SMOKE::LOCK", mode="exact"))
print(void.verify_integrity())
```

---

## Version

`v2.3.0` — Complete grounded Synthesize Intent Cells with unchanged Exact and multi-item
retrieval boundaries

---

## License

MIT License. See `LICENSE` for details.

---

## Support

- Issues: https://github.com/RaccoonStampede/Residual-Void/issues
- Discussions: https://github.com/RaccoonStampede/Residual-Void/discussions
