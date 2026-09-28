---
id: RB-cache-stampede
title: Cache Stampede and Bulk Expiry Remediation
services:
  - redis-cache
  - inventory-service
  - checkout-api
  - postgres-primary
---

# RB-cache-stampede: Cache Stampede Remediation

## Symptoms
- Redis cache hit ratio abruptly plummets (e.g. from 95%+ to under 50%).
- Database CPU spikes to 90-100% due to thundering herd query spikes.
- Read latencies across all API tiers spike simultaneously.

## Diagnostic Steps
1. Verify Redis hit ratio and eviction rates:
   `redis-cli info stats | grep keyspace`
2. Check if a scheduled bulk load or sync operation occurred with identical TTLs.
3. Inspect database queries experiencing extreme lock waits or thread saturation.

## Mitigation Steps
1. Apply probabilistic early expiration (XFetch) or request coalescing (singleflight) in application.
2. Introduce randomized jitter into cache key TTLs (e.g. base TTL + random 10-20% jitter).
3. Temporarily pre-warm high-frequency keys from a snapshot or warm script.
4. Scale up database read replicas or increase connection limits temporarily.
