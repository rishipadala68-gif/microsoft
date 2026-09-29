import json
import random
from pathlib import Path

SEED_DIR = Path("data/seed")
SEED_DIR.mkdir(parents=True, exist_ok=True)

HANDWRITTEN_INCIDENTS = [
    {
        "filename": "inc_0007_pool_exhaustion.md",
        "category": "connection_pool",
        "lookalike": "inc_0019_dns_failure.md",
        "content": """# Post-Mortem: INC-0007 Connection pool exhaustion after v212 release

## Summary
On 2024-03-12, checkout-api experienced p99 latency spike to 8s and 503 errors 10 minutes following deploy v212.

## Symptoms
- checkout-api 503s and latency spikes
- Error log: HikariPool-1 - Connection is not available, request timed out after 30000ms
- Service affected: checkout-api, postgres-primary

## Root Cause
Connection leak in retry wrapper inside `OrderClient.submit()` in file `app/clients/order_client.py` where db connections were not released on transient errors.

## Resolution Steps
1. Rollback deployment to v211.
2. Restart application pods to clear connection pool.
3. Applied runbook RB-db-pool-exhaustion.

## Stack Trace
```
Traceback (most recent call last):
  File "/app/clients/order_client.py", line 84, in submit
    conn = pool.get_connection(timeout=30)
ConnectionError: HikariPool-1 - Connection is not available, request timed out after 30000ms
```
"""
    },
    {
        "filename": "inc_0012_cert_expiry.md",
        "category": "certificate_expiry",
        "lookalike": None,
        "content": """# Post-Mortem: INC-0012 TLS certificate expired on payments-gateway

## Summary
On 2024-05-18, payments-gateway failed to establish TLS handshakes with external banking partners.

## Symptoms
- TLS handshake errors: x509: certificate has expired
- Inability to process credit card checkouts
- Service: payments-gateway

## Root Cause
Cert renewal cron silently failing after a service-account rotation in `infra/crons/renew_certs.sh`.

## Resolution Steps
1. Executed manual certificate renewal with Let's Encrypt.
2. Updated service account credentials in cron job.
3. Followed runbook RB-cert-expiry.
"""
    },
    {
        "filename": "inc_0019_dns_failure.md",
        "category": "network_dns",
        "lookalike": "inc_0007_pool_exhaustion.md",
        "content": """# Post-Mortem: INC-0019 CoreDNS pod eviction causing checkout-api timeouts

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
"""
    },
    {
        "filename": "inc_0024_cache_stampede.md",
        "category": "cache_issue",
        "lookalike": None,
        "content": """# Post-Mortem: INC-0024 Redis cache stampede during nightly bulk sync

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
"""
    }
]

CATEGORIES = [
    "connection_pool",
    "certificate_expiry",
    "network_dns",
    "cache_issue",
    "memory_leak",
    "disk_full",
    "bad_deploy",
    "queue_backlog",
    "resource_exhaustion",
    "dependency_failure",
]

LOOKALIKE_TEMPLATES = [
    ("checkout-api 503s during peak traffic", "connection_pool", "HikariPool-1 - Connection is not available after 30000ms", "RB-db-pool-exhaustion"),
    ("checkout-api 503s during peak traffic", "network_dns", "dial tcp: lookup postgres-primary: no such host", "RB-dns-resolution-failure"),
    ("orders-service latency and slow responses", "memory_leak", "java.lang.OutOfMemoryError: Java heap space", "RB-memory-leak-restart"),
    ("orders-service latency and slow responses", "queue_backlog", "Kafka consumer lag exceeding 50000 messages", "RB-queue-backlog"),
    ("payments-gateway checkout failures", "certificate_expiry", "x509: certificate has expired", "RB-cert-expiry"),
    ("payments-gateway checkout failures", "dependency_failure", "HTTP 504 Gateway Timeout from Bank API", "RB-bad-deploy-rollback"),
]


def generate_seed_data():
    labels = {}

    # Write handwritten examples
    for inc in HANDWRITTEN_INCIDENTS:
        file_path = SEED_DIR / inc["filename"]
        file_path.write_text(inc["content"], encoding="utf-8")
        labels[inc["filename"]] = {
            "root_cause_category": inc["category"],
            "lookalike_partner": inc["lookalike"],
        }

    # Generate lookalike pairs
    for i, (title_base, cat, err, rb) in enumerate(LOOKALIKE_TEMPLATES):
        fname = f"lookalike_{i+1}_{cat}.md"
        content = f"""# Incident: {title_base}

## Symptoms
- Observed: {title_base}
- Error: {err}
- Affected: checkout-api, orders-service

## Root Cause
Identified issue in {cat} causing systemic disruption.

## Resolution
1. Applied standard mitigations.
2. Executed runbook {rb}.
"""
        (SEED_DIR / fname).write_text(content, encoding="utf-8")
        labels[fname] = {"root_cause_category": cat, "lookalike_partner": f"lookalike_{i^1}_{cat}"}

    # Generate additional category incidents in mixed formats (Markdown, Jira JSON, Slack transcript)
    incident_counter = 30
    for cat in CATEGORIES:
        for j in range(5):
            incident_counter += 1
            format_type = random.choice(["md", "jira", "slack"])
            service_name = random.choice(["checkout-api", "orders-service", "inventory-service", "web-frontend", "notification-worker"])
            fname = f"inc_{incident_counter:04d}_{cat}_{j}.{ 'json' if format_type in ['jira', 'slack'] else 'md'}"

            if format_type == "md":
                content = f"""# Post-Mortem INC-{incident_counter:04d}: Outage in {service_name} due to {cat}

## Symptoms
- Service {service_name} experienced degraded performance.
- Log error: error code 500 in {service_name} at 10.0.{j}.{incident_counter}:8080.
- Services: {service_name}, postgres-primary

## Root Cause
Detailed RCA found {cat} failure in module `app/services/{service_name.replace('-', '_')}.py:handle_request`.

## Resolution Steps
1. Identified root cause in {cat}.
2. Restarted service pods.
3. Verified resolution.
"""
            elif format_type == "jira":
                content = json.dumps({
                    "issues": [{
                        "key": f"OPS-{incident_counter}",
                        "fields": {
                            "summary": f"Production Alert: {service_name} failure caused by {cat}",
                            "description": f"Service {service_name} reported critical errors. Root cause category is {cat}.\nTrace:\nFile \"app/{service_name}/handler.py\", line 42, in process\nException: {cat} exception occurred.",
                            "comment": {
                                "comments": [
                                    {"author": {"displayName": "OnCall Engineer"}, "body": f"Mitigated issue by restarting {service_name} and applying runbook RB-db-pool-exhaustion."}
                                ]
                            }
                        }
                    }]
                }, indent=2)
            else:  # slack
                content = json.dumps([
                    {"user": "alice", "text": f"@oncall {service_name} is throwing errors in prod! Sev2 incident started."},
                    {"user": "bob", "text": f"Looking at logs now. Looks like {cat} on {service_name}."},
                    {"user": "alice", "text": f"Found root cause in {cat}. Applying fix and restarting."},
                    {"user": "bob", "text": "Resolved. Latency returned to normal."}
                ], indent=2)

            (SEED_DIR / fname).write_text(content, encoding="utf-8")
            labels[fname] = {"root_cause_category": cat, "lookalike_partner": None}

    # Generate 4 near-duplicates
    for d in range(4):
        fname_dup = f"near_duplicate_{d+1}.md"
        content_dup = """# Post-Mortem: Duplicate of INC-0007 Connection Pool Issue

## Summary
Duplicate report for checkout-api 503s after v212 release on 2024-03-12.

## Symptoms
- checkout-api 503s and latency spikes
- Error log: HikariPool-1 - Connection is not available, request timed out after 30000ms
- Service: checkout-api, postgres-primary

## Root Cause
Connection leak in retry wrapper inside OrderClient.submit() in file app/clients/order_client.py where connections leaked.

## Resolution Steps
1. Rollback deployment to v211.
2. Restart application pods to clear connection pool.
"""
        (SEED_DIR / fname_dup).write_text(content_dup, encoding="utf-8")
        labels[fname_dup] = {"root_cause_category": "connection_pool", "lookalike_partner": "inc_0007_pool_exhaustion.md"}

    # Write labels file
    (SEED_DIR / "_labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"Generated {len(labels)} seed files in {SEED_DIR}")


if __name__ == "__main__":
    generate_seed_data()
