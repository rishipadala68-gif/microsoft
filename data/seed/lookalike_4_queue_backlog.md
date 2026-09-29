# Incident: orders-service latency and slow responses

## Symptoms
- Observed: orders-service latency and slow responses
- Error: Kafka consumer lag exceeding 50000 messages
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in queue_backlog causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook RB-queue-backlog.
