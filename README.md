# ResidualVoid v2.0 — Lean Permanent Core + Cryptographic Hash Chain

![Build](https://img.shields.io/badge/build-passing-brightgreen) ![Tests](https://img.shields.io/badge/tests-51%20passed-brightgreen) ![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![Version](https://img.shields.io/badge/version-2.0.0-blue)

ResidualVoid now defaults to a **lean, auditable runtime** for permanent residual storage and grounded retrieval.

This release focuses on:
- append-only residual locking,
- cryptographic chain integrity,
- strict no-invention projection behavior,
- practical secure-node and multi-network operation.

---

## What changed in v2.0

The default path has been simplified to a clean hybrid:

- ✅ **Lean permanent core** (no decay in default path, append-only residual locking)
- ✅ **Cryptographic hash chain** (`prev_hash` → `chain_hash`) with integrity verification
- ✅ **Dual projection modes** (`exact`, `synthesize`) with hard refusal gates
- ✅ **Packed 32-byte signatures** for efficient matching and ranking
- ✅ **Secure ingest/auth surface** compatible with networked use
- ✅ **Network isolation by secret** through `ResidualNetworkManager`

The following are **not part of the default execution path**:
- `mind.py`
- `geometry.py`
- Pi-Helix/autonomous/god-zone orchestration paths

They may remain in the repository as optional/experimental modules.

---

## Public API

```python
from residual_void import ResidualVoid, ResidualNetworkManager, SecureNode
```

Low-level components are also available:

```python
from residual_void import CoherentField, CoherentVoid, Residual
```

---

## Installation

```bash
git clone https://github.com/RaccoonStampede/Residual-Void.git
cd Residual-Void
pip install -r requirements.txt
pip install -e .
```

Or install directly from a release wheel:

```bash
pip install residual_void-2.0.0-py3-none-any.whl
```

---

## Quick start (single void)

```python
from residual_void import ResidualVoid

# Use a strong secret in production
void = ResidualVoid(secret="replace-with-strong-secret-string")

# Lock permanent residuals
print(void.lock("CMD::ALERT::AUTHORIZED", domain="command"))

# Project grounded output
print(void.project("CMD::ALERT", mode="exact"))
print(void.project("authorized command", mode="synthesize"))

# Verify chain integrity + status
print(void.verify_integrity())
print(void.status())
```

If you need low-level `SecureNode` access, pass `void.void` (the underlying `CoherentVoid`):

```python
from residual_void import ResidualVoid, SecureNode

void = ResidualVoid(secret="replace-with-strong-secret-string")
node = SecureNode("machine_A", void.void)

print(node.lock_text("CMD::ALERT::AUTHORIZED", domain="command"))
print(node.project("CMD::ALERT", mode="exact"))
```

---

## Multi-network usage

```python
from residual_void import ResidualNetworkManager

mgr = ResidualNetworkManager()

net1 = mgr.create_network("line_a", secret="secret-a")
net2 = mgr.create_network("line_b", secret="secret-b")

print(mgr.list_networks())
```

---

## Behavioral model

### 1) Permanent residual locking
- Residuals are append-only.
- Duplicate payloads are rejected.

### 2) Hash chain integrity
Each residual tracks:
- `prev_hash`
- `chain_hash`

Integrity verification recomputes links and detects:
- chain breaks,
- payload tampering,
- chain-tip mismatch.

### 3) Projection modes
- `exact`: returns directly grounded residuals when confidence is sufficient.
- `synthesize`: combines top grounded residual fragments.

When grounding is insufficient, the runtime refuses with a no-invention response.

---

## Security notes

- Use long, high-entropy secrets in production.
- Rotate secrets regularly.
- Prefer secret isolation per environment/tenant/network.
- In networked deployments, keep nonce/time-window validation enabled.

---

## Validation

Run tests:

```bash
python -m pytest -q
```

Minimal smoke test:

```python
from residual_void import ResidualVoid

void = ResidualVoid(secret="test-secret-32-bytes-minimum-please")

assert void.lock("SMOKE::LOCK::OK", domain="test") == "locked"
print(void.project("SMOKE::LOCK", mode="exact"))
print(void.verify_integrity())
```

---

## Version

`v2.0.0` — Lean Permanent Core + Cryptographic Hash Chain

---

## License

MIT License. See `LICENSE` for details.

---

## Support

- Issues: https://github.com/RaccoonStampede/Residual-Void/issues
- Discussions: https://github.com/RaccoonStampede/Residual-Void/discussions
