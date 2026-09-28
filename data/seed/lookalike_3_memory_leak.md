# Incident: orders-service latency and slow responses

## Symptoms
- Observed: orders-service latency and slow responses
- Error: java.lang.OutOfMemoryError: Java heap space
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in memory_leak causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-memory-leak-restart.
