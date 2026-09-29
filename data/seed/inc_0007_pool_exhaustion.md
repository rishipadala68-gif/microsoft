# Post-Mortem: INC-0007 Connection pool exhaustion after v212 release

## Summary
On 2024-03-12, checkout-api experienced p99 latency spike to 8s and 503 errors 10 minutes following deploy v212.

## Symptoms
- checkout-api 503s and latency spikes
- Error log: HikariPool-1 - Connection is not available, request timed out after 30000ms
- Service affected: checkout-api, postgres-primary

## Root Cause
Connection leak in retry wrapper inside `OrderClient.submit()` in file `app/clients/order_client.py` where db connections were not released on transient errors.

## Resolution Steps
1. Rollback deployment to v211.
2. Restart application pods to clear connection pool.
3. Applied runbook RB-db-pool-exhaustion.

## Stack Trace
```
Traceback (most recent call last):
  File "/app/clients/order_client.py", line 84, in submit
    conn = pool.get_connection(timeout=30)
ConnectionError: HikariPool-1 - Connection is not available, request timed out after 30000ms
```
