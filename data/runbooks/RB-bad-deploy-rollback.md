---
id: RB-bad-deploy-rollback
title: Automated and Manual Bad Deploy Rollback
services:
  - web-frontend
  - checkout-api
  - payments-gateway
  - orders-service
  - inventory-service
  - auth-service
  - notification-worker
---

# RB-bad-deploy-rollback: Bad Deploy Rollback

## Symptoms
- Error rate or latency spikes immediately following a canary or production release.
- Application crashes on startup (CrashLoopBackOff).
- New unhandled exceptions logged in APM/logging dashboards.

## Diagnostic Steps
1. Identify the recent deploy commit SHA or image tag:
   `git log -n 5 --oneline`
2. Compare health metrics before and after the release window.
3. Review release diff for syntax errors, missing environment variables, or schema mismatches.

## Mitigation Steps
1. Execute immediate rollback to previous stable tag:
   `kubectl rollout undo deployment/<service-name>`
2. Verify rollback completion and pod readiness:
   `kubectl rollout status deployment/<service-name>`
3. Confirm error rate drops back to baseline within 5 minutes.
4. Notify on-call team and lock pipeline until RCA is complete.
