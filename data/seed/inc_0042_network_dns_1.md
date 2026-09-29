# Post-Mortem INC-0042: Outage in web-frontend due to network_dns

## Symptoms
- Service web-frontend experienced degraded performance.
- Log error: error code 500 in web-frontend at 10.0.1.42:8080.
- Services: web-frontend, postgres-primary

## Root Cause
Detailed RCA found network_dns failure in module `app/services/web_frontend.py:handle_request`.

## Resolution Steps
1. Identified root cause in network_dns.
2. Restarted service pods.
3. Verified resolution.
