# AWS for Python backends — study sheet

> Alex holds the AWS Certified Developer – Associate (2023). Uses Lambda, SQS, ECS on Fargate,
> RDS for PostgreSQL, S3, CloudWatch, IAM and Secrets Manager. Check limits in the official docs
> before quoting a number.

## SQS

- Standard queues: at-least-once delivery and best-effort ordering. A message can be delivered
  more than once, so consumers must be idempotent.
- FIFO queues: ordering within a message group and deduplication (5-minute deduplication
  interval), with lower throughput than standard queues.
- Visibility timeout: after a consumer receives a message, it is hidden from other consumers for
  this time (default 30 seconds). If it is not deleted before the timeout, it becomes visible
  again and is redelivered. Set it longer than the processing time.
- Dead-letter queue (DLQ) with a redrive policy: after `maxReceiveCount` failed receives, the
  message moves to the DLQ. Alarm on DLQ depth.
- Message retention: default 4 days, configurable up to 14 days.
- Long polling (`WaitTimeSeconds` up to 20 seconds) reduces empty receives and cost.
- Useful metric: `ApproximateAgeOfOldestMessage` — shows when consumers fall behind.

## Lambda

- Event-driven functions; maximum timeout is 15 minutes.
- With SQS as event source, Lambda polls the queue and invokes the function with batches. Use
  partial batch responses (`ReportBatchItemFailures`) so only failed messages are retried.
- Concurrency: reserved concurrency caps a function (protects the database); cold starts add
  latency on new execution environments.
- Initialize clients and connections outside the handler so they are reused between invocations.
- Connecting many Lambdas to PostgreSQL: limit concurrency or use RDS Proxy for pooling.

## ECS (on Fargate)

- Runs Docker containers as tasks; a service keeps the desired number of tasks running behind a
  load balancer.
- Fargate: no servers to manage; you set CPU and memory per task.
- Rolling deployments by default; health checks decide when new tasks receive traffic.
- Auto scaling on CPU, memory or custom metrics (for example, queue depth).

## Other services

- RDS for PostgreSQL: managed Postgres, Multi-AZ for failover, read replicas, automated backups.
- S3: object storage; use presigned URLs for direct upload/download.
- CloudWatch: logs, metrics, alarms, dashboards. Logs Insights to query structured JSON logs.
- IAM: least privilege, one role per service; no long-lived keys in code. GitHub Actions can
  assume a role through OIDC.
- Secrets Manager (or SSM Parameter Store) for credentials, injected at runtime.
- API Gateway in front of Lambda for HTTP APIs; throttling and usage plans.

## Kubernetes (basic usage only — be honest)

- Alex deployed services with Helm charts maintained by another team and debugged with
  `kubectl get pods`, `kubectl logs` and `kubectl describe`. He did not design or operate a cluster.
- Concepts he can explain: Pod, Deployment, Service, ConfigMap, Secret, liveness and readiness
  probes, Horizontal Pod Autoscaler.

## Likely interview questions

1. SQS standard vs FIFO?
2. What is the visibility timeout and what happens if processing takes longer?
3. How do you handle a message that always fails?
4. Lambda vs ECS — when do you choose each?
5. How do you stop Lambda from exhausting database connections?
6. How do you manage secrets on AWS?
7. Have you used Kubernetes? (Basic usage only — say so.)
8. Have you used Kafka? (No production experience — pivot to SQS.)
