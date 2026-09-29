# Post-Mortem INC-0065: Outage in notification-worker due to bad_deploy

## Symptoms
- Service notification-worker experienced degraded performance.
- Log error: error code 500 in notification-worker at 10.0.4.65:8080.
- Services: notification-worker, postgres-primary

## Root Cause
Detailed RCA found bad_deploy failure in module `app/services/notification_worker.py:handle_request`.

## Resolution Steps
1. Identified root cause in bad_deploy.
2. Restarted service pods.
3. Verified resolution.
