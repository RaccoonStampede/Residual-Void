# Security

> Cross-references: [architecture.md](architecture.md) · [operations.md](operations.md) · [configuration.md](configuration.md)

---

## Threat Model Summary

| Threat | Mitigations |
|---|---|
| Replay attacks | Timestamp + nonce + kid + TTL + clock-skew window |
| Secret exfiltration | Env-var injection; no secrets in config files committed to VCS |
| Placeholder secrets in prod | Fail-fast validation in `config_loader.py` |
| Key compromise | Key rotation: active + previous key + grace window |
| Unauthorized peer | mTLS / signed message envelopes; ResidualNetworkManager enforces authN |
| Epoch forgery | CoherentVoid signs epoch-change events with active signing key |
| Persistence tampering | WAL checksums; snapshot integrity verification |

---

## Production Secret Requirements

> ⚠️ **Critical:** The following rules MUST be enforced before any production deployment.

1. **No placeholder secrets.** The config loader rejects any secret whose value matches a
   known placeholder (e.g., `CHANGE_ME`, `placeholder`, `secret`, `changeme`, `todo`, `xxx`).
2. **No default secrets.** Do not rely on hardcoded fallback values in production.
   Set all secrets via environment variables.
3. **Minimum entropy.** Secret keys must be at least 32 characters (256-bit random recommended).
4. **Rotation.** Secrets must be rotatable without downtime using the key-rotation model below.

Relevant config keys: `security.secret_key`, `security.signing_key`.  
See [configuration.md](configuration.md#security) for full details.

---

## Replay Protection

Inter-component messages (and all external inputs processed by ResidualNetworkManager) carry
a signed envelope with the following claims:

| Claim | Type | Description |
|---|---|---|
| `kid` | string | Key ID identifying which signing key was used |
| `iat` | int (Unix epoch) | Issued-at timestamp |
| `exp` | int (Unix epoch) | Expiry timestamp (`iat + TTL`) |
| `nonce` | string (UUID v4) | Per-message random nonce |

### TTL and Skew Handling

- Default TTL: **30 seconds** (configurable: `security.token_ttl_seconds`).
- Maximum allowed clock skew: **10 seconds** (configurable: `security.max_clock_skew_seconds`).
- Effective acceptance window: `[iat - skew, exp + skew]`.

```
                 iat          exp
                  │            │
──────────────────┼────────────┼──────────────▶ time
        ◀─ skew ─▶│            │◀─ skew ─▶
        │                                 │
        └── acceptance window (iat-skew) ─┘
                               to (exp+skew)
```

### Nonce Replay Detection

- Each received nonce is stored in a short-lived nonce cache keyed by `nonce` value.
- Cache TTL = `token_ttl + 2 * max_clock_skew` seconds.
- If a nonce is seen a second time within its cache window the message is rejected with
  `REPLAY_DETECTED`.
- Cache backend: in-memory LRU (default) or Redis (configurable:
  `security.nonce_cache_backend`).

### Validation Flow (ResidualNetworkManager)

```
Receive message
    │
    ├─ 1. Verify signature with kid → active key (or previous key if in grace window)
    ├─ 2. Check exp ≥ now - skew  (not expired beyond skew)
    ├─ 3. Check iat ≤ now + skew  (not issued in the future beyond skew)
    ├─ 4. Look up nonce in cache  (reject if present)
    ├─ 5. Insert nonce into cache with TTL
    └─ 6. Accept message
```

---

## Key Rotation Model

### Key Inventory

| Slot | Config key | Description |
|---|---|---|
| Active | `security.signing_key` | Current key used to sign new messages |
| Previous | `security.previous_signing_key` | Accepted for verification during grace window |

### Rotation Procedure

1. **Generate new key.** Create a new high-entropy signing key.
2. **Promote current → previous.** Set `security.previous_signing_key` = current active value.
3. **Deploy new active key.** Set `security.signing_key` = new key. Deploy rolling.
4. **Wait grace window.** Default: **300 seconds** (`security.key_rotation_grace_seconds`).
   During this window, tokens signed by the previous key are still accepted.
5. **Clear previous key.** After grace window expires, remove `security.previous_signing_key`.
6. **Verify.** Confirm no validation errors referencing the old `kid` in logs.

### Grace Window

```
t=0    Deploy new active key
t=0…G  Both active and previous keys accepted (G = grace_window)
t>G    Only active key accepted; previous key rejected
```

### Rollback Notes

- If the new key causes issues during the grace window, set `security.signing_key` back to
  the previous value and promote `security.previous_signing_key` to `security.signing_key`.
- This is safe because both keys are valid during the grace window.
- After rollback, generate a new candidate key and re-run the procedure from step 1.
- **Do not reuse a key that has been compromised.** Treat a compromised key as requiring
  immediate emergency rotation with zero grace window.

---

## mTLS / Transport Security

- All peer-to-peer communication between ResidualNetworkManager instances MUST use mTLS in
  production.
- Certificate rotation follows the same grace-window pattern as signing keys.
- Certificate pinning is optional but recommended for fixed-topology deployments.

---

## Audit Logging

- Authentication events (accept / reject) are logged at `INFO` level with `kid`, `nonce`
  hash, and outcome.
- Replay detection events are logged at `WARNING` level.
- Key rotation events are logged at `INFO` level.
- **Do not log raw secret values or full tokens.**

---

## Security Checklist (Pre-Production)

- [ ] All placeholder secret values replaced
- [ ] `APP_ENV=production` set and config loader validates secrets
- [ ] mTLS certificates provisioned and deployed
- [ ] NTP synchronized on all nodes (skew < 5 s)
- [ ] Nonce cache backend selected and capacity-planned
- [ ] Key rotation procedure tested in staging
- [ ] Audit log shipping configured
- [ ] Penetration test scheduled
