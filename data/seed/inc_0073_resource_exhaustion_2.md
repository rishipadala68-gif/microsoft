# Post-Mortem INC-0073: Outage in notification-worker due to resource_exhaustion

## Symptoms
- Service notification-worker experienced degraded performance.
- Log error: error code 500 in notification-worker at 10.0.2.73:8080.
- Services: notification-worker, postgres-primary

## Root Cause
Detailed RCA found resource_exhaustion failure in module `app/services/notification_worker.py:handle_request`.

## Resolution Steps
1. Identified root cause in resource_exhaustion.
2. Restarted service pods.
3. Verified resolution.
