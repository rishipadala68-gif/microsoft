# Post-Mortem: INC-0024 Redis cache stampede during nightly bulk sync

## Summary
On 2024-08-04, redis-cache hit ratio fell from 96% to 41% after mass key expiry, driving postgres-primary CPU to 95%.

## Symptoms
- Redis hit ratio drop
- Database CPU spike on postgres-primary
- Services: redis-cache, inventory-service, postgres-primary

## Root Cause
Identical TTLs on nightly bulk load causing simultaneous cache miss stampede in `app/cache/bulk_sync.py:sync_inventory`.

## Resolution Steps
1. Injected randomized jitter into cache key TTLs.
2. Added request coalescing (singleflight) in inventory-service.
3. Followed runbook RB-cache-stampede.
