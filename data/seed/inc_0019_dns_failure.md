# Post-Mortem: INC-0019 CoreDNS pod eviction causing checkout-api timeouts

## Summary
On 2024-06-22, checkout-api threw 503s and connection timeouts, initially resembling database pool exhaustion.

## Symptoms
- checkout-api 503s and request timeouts
- Error: dial tcp: lookup postgres-primary on 10.96.0.10:53: no such host
- Service: checkout-api, postgres-primary

## Root Cause
CoreDNS pods evicted after node pressure on cluster worker node; hostname postgres-primary failed to resolve.

## Resolution Steps
1. Restarted CoreDNS deployment across surviving nodes.
2. Added PodDisruptionBudget to CoreDNS.
3. Followed runbook RB-dns-resolution-failure.
