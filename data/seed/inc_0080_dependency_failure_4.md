# Post-Mortem INC-0080: Outage in web-frontend due to dependency_failure

## Symptoms
- Service web-frontend experienced degraded performance.
- Log error: error code 500 in web-frontend at 10.0.4.80:8080.
- Services: web-frontend, postgres-primary

## Root Cause
Detailed RCA found dependency_failure failure in module `app/services/web_frontend.py:handle_request`.

## Resolution Steps
1. Identified root cause in dependency_failure.
2. Restarted service pods.
3. Verified resolution.
