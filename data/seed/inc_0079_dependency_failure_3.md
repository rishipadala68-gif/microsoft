# Post-Mortem INC-0079: Outage in notification-worker due to dependency_failure

## Symptoms
- Service notification-worker experienced degraded performance.
- Log error: error code 500 in notification-worker at 10.0.3.79:8080.
- Services: notification-worker, postgres-primary

## Root Cause
Detailed RCA found dependency_failure failure in module `app/services/notification_worker.py:handle_request`.

## Resolution Steps
1. Identified root cause in dependency_failure.
2. Restarted service pods.
3. Verified resolution.
