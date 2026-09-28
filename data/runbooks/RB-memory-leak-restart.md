---
id: RB-memory-leak-restart
title: Memory Leak Mitigation and Graceful Restart
services:
  - orders-service
  - checkout-api
  - notification-worker
---

# RB-memory-leak-restart: Memory Leak Remediation

## Symptoms
- Monotonically increasing memory usage over hours or days without dropping after GC.
- Pods killed with exit code 137 (OOMKilled).
- Degrading throughput and severe GC pause times before container termination.

## Diagnostic Steps
1. Identify pods experiencing OOM terminations:
   `kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' | grep OOMKilled`
2. Inspect JVM/Node heap metrics in Prometheus:
   `sum(container_memory_working_set_bytes{container="orders-service"}) by (pod)`
3. Trigger and capture heap dump for offline analysis if possible.

## Mitigation Steps
1. Execute immediate staggered rolling restart to clear leaked memory buffers:
   `kubectl rollout restart deployment/<service-name>`
2. Temporarily increase container memory limit to provide headroom:
   `kubectl set resources deployment/<service-name> --limits=memory=4Gi`
3. Schedule emergency patch release to fix identified memory retention.
