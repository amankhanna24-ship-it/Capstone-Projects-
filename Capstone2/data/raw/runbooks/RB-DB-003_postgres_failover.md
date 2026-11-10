# RB-DB-003 — PostgreSQL primary failover

**Owner:** Platform Engineering · **Applies to:** `pg-core` cluster (Patroni, 3 nodes) · **Last reviewed:** 20 Feb 2026

## When to use
Use this runbook when the primary database `pg-core-1` is unavailable for more than 2 minutes and Patroni has **not** failed over automatically, or when a planned switchover is required for maintenance.

## Pre-checks
1. Confirm the primary is really down: `patronictl -c /etc/patroni.yml list`.
2. Check replication lag on the replicas; do **not** promote a replica that is more than 30 seconds behind unless the Incident Manager approves data loss.
3. Freeze deployments in the release pipeline.

## Promote a replica to primary
1. Run `patronictl -c /etc/patroni.yml failover --candidate pg-core-2`.
2. Confirm the new leader with `patronictl list` — `pg-core-2` must show role `Leader`.
3. The PgBouncer pool picks up the new primary through the Consul service `pg-core-primary`; verify with `psql -h pg-core-primary.service -c "select pg_is_in_recovery();"` which must return `f`.
4. Run the smoke test job `db-smoke` in the CI pipeline.

## Rebuild the old primary
Once the old node is healthy, re-initialise it as a replica: `patronictl reinit pg-core pg-core-1`. Monitor replication until lag is under 1 second.

## Rollback
If the new primary misbehaves within 15 minutes, switch back with `patronictl switchover --candidate pg-core-1` provided its data is intact.

## Communication
Post in `#inc-bridge` at each step. The RPO target for `pg-core` is 30 seconds and the RTO target is 15 minutes.
