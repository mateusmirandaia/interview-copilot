# System design — study sheet (backend and payments)

## How to answer a design question

1. Clarify requirements: users, main flows, scale (requests per second, data size), latency,
   consistency needs. Ask, do not assume.
2. Start simple: one API service, one PostgreSQL database. Say it out loud.
3. Draw the main flow, then find the bottleneck or failure point and fix only that.
4. Talk about failures: retries, timeouts, duplicates, what happens if a component is down.
5. Finish with observability and how you would roll it out.

## Building blocks

- **Stateless API** behind a load balancer → scale horizontally by adding instances.
- **Database:** indexes first, then connection pooling, read replicas for reads, partitioning
  for very large tables, sharding only when really needed.
- **Cache (Redis):** cache-aside (read cache, on miss read DB and write cache with a TTL);
  invalidate on writes or events; protect against stampede (lock or early refresh). Never the
  source of truth for money.
- **Queues (SQS, Celery):** move slow or unreliable work out of the request; absorb spikes;
  retries with backoff; dead-letter queue.
- **Rate limiting:** token bucket or fixed/sliding window, often in Redis or at the API gateway.
- **Timeouts and retries:** every network call has a timeout; retry only idempotent operations,
  with exponential backoff and jitter; circuit breaker for a failing dependency.

## Idempotency

- An operation is idempotent if doing it twice has the same effect as doing it once.
- Pattern for APIs: the client sends an `Idempotency-Key` header. The server stores the key with
  the request result under a unique constraint. A repeated key returns the stored result instead
  of executing again.
- Pattern for consumers: store the message or event ID in a table with a unique constraint, in the
  same transaction as the side effect (`INSERT ... ON CONFLICT DO NOTHING`).
- Exactly-once delivery is not realistic across networks; aim for at-least-once delivery +
  idempotent processing.

## Consistency patterns

- **Transactional outbox:** write the business change and an "outbox" event row in the same DB
  transaction; a separate relay publishes the events to the queue. Avoids "saved in DB but
  message lost" or the reverse.
- **Saga:** a sequence of local transactions with compensating actions instead of a distributed
  transaction.
- **Double-entry ledger (payments):** every movement is recorded as balanced debit and credit
  entries; entries are append-only (corrections are new entries); balances are derived.
- Use exact decimal types for money (`NUMERIC` in Postgres, `Decimal` in Python), or integer
  minor units (cents) — never floats.

## Observability

- Three signals: logs (structured JSON with a correlation or request ID), metrics (rate, errors,
  duration; queue age), traces (OpenTelemetry, distributed spans).
- Alert on symptoms users feel (error rate, latency, queue age), not on every CPU spike.
- Dashboards per service; runbooks linked from alerts; postmortems without blame.

## Example scenario: payment webhook / notification service

- Intake endpoint validates the signature, stores the raw event, enqueues it, returns 2xx fast.
- Consumers process idempotently by event ID; dead-letter queue + alarm; replay tool for the DLQ.
- Outgoing webhooks to merchants: retries with exponential backoff, signed payloads, delivery
  log per attempt, merchant-visible status.

## Likely interview questions

1. How would you scale an API from 100 to 10,000 requests per second?
2. How would you design a payment webhook system?
3. How do you make an operation idempotent?
4. What is the transactional outbox pattern?
5. Where would you use a cache, and how do you invalidate it?
6. How do you design for failures of a third-party API?
7. How do you know your system is healthy in production?
