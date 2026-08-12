# Operations

> Cross-references: [architecture.md](architecture.md) · [security.md](security.md) · [configuration.md](configuration.md)

---

## Production Readiness Checklist

- [ ] Config validated with `APP_ENV=production python src/config_loader.py --validate`
- [ ] All placeholder secrets replaced (see [security.md](security.md))
- [ ] Database migrations applied; WAL mode confirmed
- [ ] Snapshot directory provisioned with correct permissions
- [ ] NTP synchronized on all cluster nodes
- [ ] mTLS certificates deployed
- [ ] Log shipping configured
- [ ] Alerting thresholds set (see [Monitoring](#monitoring))
- [ ] Backup schedule verified
- [ ] Runbook tested in staging

---

## Persistence

### Storage Backends

| Component | Recommended Backend | Mode |
|---|---|---|
| ResidualVoid | PostgreSQL (prod) / SQLite (dev) | WAL |
| CoherentVoid | Same as ResidualVoid (shared or separate schema) | WAL |
| ResidualFieldMind | Object storage or local filesystem | Append-only blobs |

### WAL Configuration

For SQLite:
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;   -- safe with WAL; FULL for maximum durability
PRAGMA wal_autocheckpoint=1000;
```

For PostgreSQL, WAL is always on. Ensure:
- `wal_level = replica` (minimum)
- `archive_mode = on` and `archive_command` configured for PITR

### Snapshots

- ResidualVoid takes a coherence-state snapshot every `persistence.snapshot_interval_seconds`
  (default: 300 s).
- Snapshots are written atomically: new file written then renamed into place.
- Snapshot naming convention: `residualvoid-snapshot-{epoch_id}-{unix_ts}.bin`
- At most `persistence.snapshot_retain_count` (default: 10) snapshots are retained;
  older ones are pruned automatically.
- Snapshots are stored at `persistence.snapshot_dir` (default: `./data/snapshots/`).

### Recovery Semantics

1. **Normal startup:** Loads the latest valid snapshot, then replays WAL from the snapshot
   checkpoint forward.
2. **Snapshot corruption:** If the latest snapshot fails integrity check, the previous
   snapshot is used. If all snapshots are corrupt, a full WAL replay from the beginning is
   attempted.
3. **WAL corruption:** Log a `CRITICAL` error, halt the affected component, alert on-call.
   Manual recovery from backup is required.
4. **Partial replay:** ResidualVoid applies idempotent contribution semantics; re-applying
   already-seen contributions is safe.
5. **Cold start (no data):** Component initializes with an empty residual field and
   bootstraps coherence from seed peers via CoherentVoid.

### Backup Schedule (Recommended)

| Backup type | Frequency | Retention |
|---|---|---|
| Continuous WAL archive | Continuous | 7 days |
| Daily snapshot export | Daily 02:00 UTC | 30 days |
| Weekly full dump | Weekly Sunday 03:00 UTC | 90 days |

---

## Monitoring

### Key Metrics

| Metric | Alert threshold | Notes |
|---|---|---|
| `residualvoid.coherence_lag_ms` | > 500 ms (warn), > 2000 ms (crit) | Coherence propagation delay |
| `residualvoid.field_contributions_dropped` | > 0 (warn) | Dropped contributions |
| `residualvoid.replay_detections_total` | > 10/min (warn) | Possible replay attack |
| `coherentvoid.epoch_failures_total` | > 0 (crit) | Epoch consensus failure |
| `residualnetwork.peer_count` | < 2 (crit) | Below quorum |
| `residualnetwork.auth_failures_total` | > 5/min (warn) | Auth errors |
| `process.resident_memory_bytes` | > 80% limit (warn) | Memory pressure |

### Health Endpoints

Each component exposes:
- `GET /healthz` — liveness probe (returns 200 if process is running)
- `GET /readyz` — readiness probe (returns 200 only if component is ready to serve)

---

## Runbook

### Component Won't Start

1. Check logs for `CRITICAL` or `ERROR` messages at startup.
2. Run `python src/config_loader.py --validate config/residualvoid.yaml` to verify config.
3. Confirm `APP_ENV` matches intended environment.
4. Check database connectivity and WAL mode.
5. Verify NTP synchronization (`chronyc tracking` or `timedatectl`).

### Replay Detection Spike

1. Check `residualnetwork.replay_detections_total` — if > 50/min, alert security team.
2. Inspect auth logs for the source IP / peer ID triggering replays.
3. If a key is suspected compromised, initiate emergency key rotation (zero grace window).
4. Temporarily block the offending peer in `network.blocked_peers` config.

### CoherentVoid Epoch Failure

1. Check cluster node count — must be ≥ 3 with quorum = 2.
2. Inspect CoherentVoid logs for `epoch_failure` events.
3. If two nodes are healthy, the third may need restart or recovery.
4. Initiate manual snapshot + recovery on the affected node.

### Key Rotation

See [security.md#key-rotation-model](security.md#key-rotation-model) for the full procedure.

### Snapshot Recovery

```bash
# List available snapshots
ls -lt data/snapshots/

# Force startup from a specific snapshot (set in config)
# persistence.snapshot_restore_path: data/snapshots/residualvoid-snapshot-42-1700000000.bin

# Then restart the component
```

---

## Capacity Planning

| Resource | Development | Production (3-node) |
|---|---|---|
| CPU | 2 cores | 8 cores / node |
| Memory | 1 GB | 16 GB / node |
| Disk (WAL + snapshots) | 5 GB | 500 GB / node |
| Network | 100 Mbps | 1 Gbps |
| Nonce cache (Redis, if used) | — | 2 GB |

---

## Upgrade Procedure

1. Deploy new version to one node at a time (rolling).
2. Verify `/readyz` on the new node before proceeding.
3. Monitor coherence lag during rollout.
4. If coherence lag exceeds 2 s or epoch failures occur, roll back the updated node.
5. After full rollout, confirm all nodes are on the same version.
6. Apply any pending DB migrations after all nodes are updated.
