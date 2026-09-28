# Post-Mortem INC-0059: Outage in inventory-service due to disk_full

## Symptoms
- Service inventory-service experienced degraded performance.
- Log error: error code 500 in inventory-service at 10.0.3.59:8080.
- Services: inventory-service, postgres-primary

## Root Cause
Detailed RCA found disk_full failure in module `app/services/inventory_service.py:handle_request`.

## Resolution Steps
1. Identified root cause in disk_full.
2. Restarted service pods.
3. Verified resolution.
