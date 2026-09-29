---
id: RB-dns-resolution-failure
title: DNS Resolution and CoreDNS Failure Remediation
services:
  - checkout-api
  - orders-service
  - web-frontend
  - postgres-primary
---

# RB-dns-resolution-failure: DNS Resolution Failure

## Symptoms
- Logs show `no such host`, `connection timed out: i/o timeout`, or `Temporary failure in name resolution`.
- Upstream service calls fail with DNS lookup errors.
- Inability to resolve internal hostnames like `postgres-primary` or external third-party APIs.

## Diagnostic Steps
1. Test in-pod DNS resolution:
   `kubectl exec -it <pod-name> -- nslookup postgres-primary`
2. Check CoreDNS pod status and resource limits:
   `kubectl get pods -n kube-system -l k8s-app=kube-dns`
3. Inspect CoreDNS logs for upstream forwarding timeouts or rate-limiting:
   `kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100`

## Mitigation Steps
1. Restart degraded CoreDNS pods to clear bad state or stale caches:
   `kubectl rollout restart deployment/coredns -n kube-system`
2. Scale up CoreDNS replicas to handle DNS query spikes:
   `kubectl scale deployment/coredns -n kube-system --replicas=5`
3. Verify PodDisruptionBudget (PDB) is present to prevent concurrent node eviction:
   `kubectl get pdb -n kube-system`
