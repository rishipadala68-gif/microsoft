# Incident: checkout-api 503s during peak traffic

## Symptoms
- Observed: checkout-api 503s during peak traffic
- Error: dial tcp: lookup postgres-primary: no such host
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in network_dns causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-dns-resolution-failure.
