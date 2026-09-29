# Post-Mortem INC-0039: Outage in checkout-api due to certificate_expiry

## Symptoms
- Service checkout-api experienced degraded performance.
- Log error: error code 500 in checkout-api at 10.0.3.39:8080.
- Services: checkout-api, postgres-primary

## Root Cause
Detailed RCA found certificate_expiry failure in module `app/services/checkout_api.py:handle_request`.

## Resolution Steps
1. Identified root cause in certificate_expiry.
2. Restarted service pods.
3. Verified resolution.
