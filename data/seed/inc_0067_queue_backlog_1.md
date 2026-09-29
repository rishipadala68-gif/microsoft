# Post-Mortem INC-0067: Outage in checkout-api due to queue_backlog

## Symptoms
- Service checkout-api experienced degraded performance.
- Log error: error code 500 in checkout-api at 10.0.1.67:8080.
- Services: checkout-api, postgres-primary

## Root Cause
Detailed RCA found queue_backlog failure in module `app/services/checkout_api.py:handle_request`.

## Resolution Steps
1. Identified root cause in queue_backlog.
2. Restarted service pods.
3. Verified resolution.
