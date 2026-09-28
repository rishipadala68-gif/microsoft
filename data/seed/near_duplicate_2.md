# Post-Mortem: Duplicate of INC-0007 Connection Pool Issue

## Summary
Duplicate report for checkout-api 503s after v212 release on 2024-03-12.

## Symptoms
- checkout-api 503s and latency spikes
- Error log: HikariPool-1 - Connection is not available, request timed out after 30000ms
- Service: checkout-api, postgres-primary

## Root Cause
Connection leak in retry wrapper inside OrderClient.submit() in file app/clients/order_client.py where connections leaked.

## Resolution Steps
1. Rollback deployment to v211.
2. Restart application pods to clear connection pool.
