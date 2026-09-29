# Post-Mortem INC-0070: Outage in notification-worker due to queue_backlog

## Symptoms
- Service notification-worker experienced degraded performance.
- Log error: error code 500 in notification-worker at 10.0.4.70:8080.
- Services: notification-worker, postgres-primary

## Root Cause
Detailed RCA found queue_backlog failure in module `app/services/notification_worker.py:handle_request`.

## Resolution Steps
1. Identified root cause in queue_backlog.
2. Restarted service pods.
3. Verified resolution.
