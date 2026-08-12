# Residual-Void

> **Production status:** Pre-production. Review [docs/security.md](docs/security.md) and
> [docs/operations.md](docs/operations.md) before deploying to any internet-facing environment.

Residual-Void is a distributed coherence engine composed of four primary components:

| Component | Role |
|---|---|
| **ResidualVoid** | Core residual-field accumulation and coherence boundary manager |
| **CoherentVoid** | Consensus and coherence-state propagation layer |
| **ResidualFieldMind** | Decision and inference engine operating over residual fields |
| **ResidualNetworkManager** | Network topology, peer discovery, and message routing |

---

## Table of Contents

1. [Quickstart](#quickstart)
2. [Configuration](#configuration)
3. [Security](#security)
4. [Operations](#operations)
5. [Documentation](#documentation)
6. [Development](#development)

---

## Quickstart

```bash
# 1. Copy example config and edit for your environment
cp config/residualvoid.example.yaml config/residualvoid.yaml

# 2. Set environment variables (production)
export APP_ENV=production
export RESIDUALVOID_SECRET_KEY=<your-strong-secret>   # never use the placeholder
export RESIDUALVOID_SIGNING_KEY=<your-signing-key>

# 3. Validate config (will fail-fast on placeholder secrets in production)
python src/config_loader.py --validate config/residualvoid.yaml

# 4. Run
python -m residualvoid
```

> ⚠️ **Never run in production with placeholder secrets.** The config loader will reject
> any secret that matches a known placeholder value when `APP_ENV=production`.

---

## Configuration

The primary configuration file is `config/residualvoid.yaml` (not committed to source control).
Start from the annotated example:

```
config/residualvoid.example.yaml
```

Key environment variables:

| Variable | Required in Prod | Description |
|---|---|---|
| `APP_ENV` | Recommended | `development` \| `staging` \| `production` (default: `development`) |
| `RESIDUALVOID_SECRET_KEY` | **Yes** | HMAC/signing master secret |
| `RESIDUALVOID_SIGNING_KEY` | **Yes** | JWT / message signing key |
| `RESIDUALVOID_DB_URL` | **Yes** | Persistence layer connection string |

See [docs/configuration.md](docs/configuration.md) for the full config reference.

---

## Security

- All inter-component messages carry a signed token with `kid`, `nonce`, `iat`, and `exp`.
- The system implements replay-attack protection using timestamp + nonce + TTL + skew window.
- Key rotation is supported with an active key and a previous-key grace window.
- **Placeholder secrets are rejected at startup in production.**

See [docs/security.md](docs/security.md) for the threat model and controls.

---

## Operations

- Persistence uses WAL mode with periodic snapshots.
- Recovery semantics and snapshot strategy are documented in [docs/operations.md](docs/operations.md).
- Production readiness checklist is available in [docs/operations.md#production-readiness-checklist](docs/operations.md#production-readiness-checklist).

---

## Documentation

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Component architecture and data-flow |
| [docs/security.md](docs/security.md) | Threat model, replay protection, key rotation |
| [docs/operations.md](docs/operations.md) | Runbook, persistence, recovery |
| [docs/configuration.md](docs/configuration.md) | Full config reference and migration guide |
| [docs/test-traceability.md](docs/test-traceability.md) | Requirements-to-test traceability matrix |
| [docs/roadmap.md](docs/roadmap.md) | Engineering roadmap and prioritization |
| [docs/adr/0001-production-baseline.md](docs/adr/0001-production-baseline.md) | ADR: Production baseline decisions |

---

## Development

```bash
pip install -r requirements.txt   # if present
python -m pytest                  # run tests
APP_ENV=development python src/config_loader.py --validate config/residualvoid.example.yaml
```

---

## License

See `LICENSE` for details.
