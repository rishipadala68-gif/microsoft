# Incident: payments-gateway checkout failures

## Symptoms
- Observed: payments-gateway checkout failures
- Error: HTTP 504 Gateway Timeout from Bank API
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in dependency_failure causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-bad-deploy-rollback.
