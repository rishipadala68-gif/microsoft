---
id: RB-db-pool-exhaustion
title: Database Connection Pool Exhaustion Remediation
services:
  - checkout-api
  - orders-service
  - inventory-service
  - postgres-primary
---

# RB-db-pool-exhaustion: Database Connection Pool Exhaustion

## Symptoms
- HTTP 503 Service Unavailable or p99 latency spikes above 5s.
- Log error: `Connection is not available, request timed out after 30000ms` (HikariPool / psycopg pool).
- Database active connection count near or at `max_connections`.

## Diagnostic Steps
1. Verify database active connection count:
   `SELECT count(*), state FROM pg_stat_activity GROUP BY state;`
2. Identify services holding open idle-in-transaction connections:
   `SELECT pid, now() - xact_start AS duration, query FROM pg_stat_activity WHERE state = 'idle in transaction' ORDER BY duration DESC;`
3. Check recent service deploys for leaked connections or retry wrappers.

## Mitigation Steps
1. Immediate relief: Terminate stuck idle connections exceeding 2 minutes:
   `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - xact_start > interval '2 minutes';`
2. If connection leak was triggered by a recent deploy, rollback to previous release.
3. Temporarily increase application pool size or deploy PgBouncer connection pooling.
4. Restart application pods with rolling restart to reset pools.
