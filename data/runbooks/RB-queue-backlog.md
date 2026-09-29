---
id: RB-queue-backlog
title: Message Queue Backlog and Consumer Lag Remediation
services:
  - kafka-orders
  - orders-service
  - notification-worker
---

# RB-queue-backlog: Kafka Message Queue Backlog

## Symptoms
- Consumer lag steadily accumulating across Kafka topic partitions.
- Downstream processing latency increasing from seconds to hours.
- Unprocessed events accumulating in consumer group offsets.

## Diagnostic Steps
1. Measure consumer lag per partition:
   `kafka-consumer-groups.sh --bootstrap-server kafka-orders:9092 --describe --group order-processors`
2. Check consumer logs for poison-pill messages, infinite retries, or slow external calls.
3. Verify Kafka broker disk I/O and network saturation.

## Mitigation Steps
1. Scale out consumer worker pods up to the total partition count:
   `kubectl scale deployment/notification-worker --replicas=12`
2. If blocked by a poisoned message, configure dead-letter queue (DLQ) routing to bypass the poison pill.
3. Temporarily increase consumer batch size and polling timeouts.
