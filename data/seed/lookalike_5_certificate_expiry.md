# Incident: payments-gateway checkout failures

## Symptoms
- Observed: payments-gateway checkout failures
- Error: x509: certificate has expired
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in certificate_expiry causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-cert-expiry.
