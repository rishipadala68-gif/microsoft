---
id: RB-disk-full
title: Disk Capacity and Inode Exhaustion Remediation
services:
  - postgres-primary
  - kafka-orders
  - orders-service
---

# RB-disk-full: Disk Space / Inode Exhaustion

## Symptoms
- Filesystem write failures: `No space left on device` or `No space left on device (os error 28)`.
- CrashLoopBackOff or pod evictions with `DiskPressure`.
- Database write aborts (WAL write errors, disk full panics).

## Diagnostic Steps
1. Check filesystem disk space and inode utilization:
   `df -h && df -i`
2. Identify top space-consuming directories:
   `du -sh /* 2>/dev/null | sort -hr | head -n 10`
3. Check for oversized or unrotated container logs:
   `du -sh /var/log/* /var/lib/docker/containers/* 2>/dev/null | sort -hr | head -n 5`

## Mitigation Steps
1. Prune unused docker images and dangling volumes:
   `docker system prune -af --volumes`
2. Truncate unrotated log files:
   `truncate -s 0 /var/log/*.log`
3. Clean temporary files and package caches:
   `rm -rf /tmp/* ~/.cache/*`
4. Expand storage volume (PVC / EBS) dynamically if cloud-provisioned.
