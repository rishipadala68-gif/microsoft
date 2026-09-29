# Incident: checkout-api 503s during peak traffic

## Symptoms
- Observed: checkout-api 503s during peak traffic
- Error: HikariPool-1 - Connection is not available after 30000ms
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in connection_pool causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-db-pool-exhaustion.
