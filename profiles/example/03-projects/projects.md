# Projects — Alex Morgan (real cases)

> The ONLY source of stories. When the interviewer asks "tell me about a time...", "give me an
> example" or "where did you do X?", use one case from this file, exactly as written.
> Each case has a **Keywords** line: distinctive words used by the evals to detect which case an
> answer cites (two cases can share a company, so the company name alone is not enough).
> Pick the case with the "Topic → case map" below. One case per answer. Never mix cases,
> never add reasons, dates, lessons or numbers that are not written here.

## Topic → case map

| Topic | Case |
|---|---|
| Idempotency, duplicate events, retries | Shipment events pipeline |
| Queues, event-driven design, async processing | Shipment events pipeline |
| AWS SQS, Lambda, dead-letter queue | Shipment events pipeline |
| Webhooks, system design of an event intake | Shipment events pipeline |
| Caching, Redis | Tracking API latency |
| API performance, scaling an API, FastAPI | Tracking API latency |
| Profiling, measuring before optimizing | Tracking API latency |
| Technical disagreement, conflict with a colleague | Tracking API latency |
| Database indexing, slow query, EXPLAIN ANALYZE | Appointment report query |
| Django ORM performance, PostgreSQL | Appointment report query |
| Failure, mistake, incident, postmortem | Duplicate reminder incident |
| Celery, background jobs | Duplicate reminder incident |
| Observability, monitoring, alerting, logging | Duplicate reminder incident |
| Testing strategy, pytest, flaky tests | CI pipeline speed-up |
| CI/CD, GitHub Actions, deploy frequency, Docker | CI pipeline speed-up |
| Data engineering, pandas, Airflow, ETL | Nightly sales ETL |
| Memory problems, large datasets | Nightly sales ETL |

---

## Shipment events pipeline

- **Company:** Contoso Logistics (2023).
- **Keywords:** shipment events, webhook intake, carriers
- **Problem:** carriers send shipment status updates by webhook. The FastAPI endpoint processed
  each event synchronously and called slow downstream services. Carriers timed out and
  retried, so 4% of webhook calls failed with timeouts and some status updates were applied
  twice.
- **What Alex did:** he designed and built the new intake. The endpoint now only validates the
  payload, stores the raw event and publishes it to an SQS standard queue, then returns 202.
  Lambda functions consume the queue. Because SQS standard delivers at least once, every
  consumer is idempotent: the carrier event ID goes into a `processed_events` table with a
  unique constraint, using `INSERT ... ON CONFLICT DO NOTHING`, in the same transaction as the
  status update. Messages that fail 5 times go to a dead-letter queue, with a CloudWatch
  alarm on the dead-letter queue depth and on the age of the oldest message.
- **Technologies:** FastAPI, SQS, Lambda, PostgreSQL (RDS), CloudWatch.
- **Result:** volume of 2 million events per day. Webhook timeouts went from 4% to 0.1%.
  Endpoint p95 latency went from 2.5 seconds to 80 ms. Zero duplicate status updates since
  launch.

**EN (spoken):** "At Contoso Logistics, carrier webhooks were processed synchronously, so 4% of
the calls timed out and some updates were applied twice. I changed the endpoint to validate,
store the event, publish it to SQS and return 202. Lambda consumers process the queue, and
each one is idempotent: the event ID has a unique constraint in Postgres, in the same
transaction as the update. Timeouts went from 4% to 0.1%, and we have had zero duplicates."

## Tracking API latency

- **Company:** Contoso Logistics (2024).
- **Keywords:** tracking API, N+1, rewrite in Go
- **Problem:** the public tracking API (FastAPI) is used by the customer portal and partners.
  Its p95 latency was 900 ms at peak. The tech lead proposed rewriting the service in Go.
- **What Alex did:** he disagreed with the rewrite and asked for a one-week profiling spike
  first, so the decision would be based on data. The tech lead agreed. Profiling with py-spy
  and query logging showed an N+1 problem: 12 SQL queries per request. Alex fixed the
  SQLAlchemy loading (selectinload), which brought it to 2 queries per request, and added a
  Redis cache-aside for the shipment summary, with a 30-second TTL and invalidation when a
  status-change event arrives. The tech lead reviewed the results and the rewrite was dropped.
- **Technologies:** FastAPI, SQLAlchemy, PostgreSQL, Redis, py-spy.
- **Result:** p95 went from 900 ms to 120 ms. Database CPU at peak went from 70% to 35%. The
  service handled the Black Friday peak, 3 times the normal traffic, with the same 4
  containers. No rewrite was needed.

**EN (spoken):** "At Contoso Logistics, our tracking API had a p95 of 900 milliseconds, and the
tech lead wanted to rewrite it in Go. I asked for one week of profiling first. We found an N+1
problem, 12 queries per request. I fixed the loading to 2 queries and added a Redis
cache-aside with a 30-second TTL, invalidated on status changes. p95 went to 120
milliseconds, and we handled Black Friday with the same 4 containers. No rewrite."

## Appointment report query

- **Company:** Fabrikam Health (2021).
- **Keywords:** appointment report, EXPLAIN ANALYZE, composite index
- **Problem:** the monthly appointment report in the Django app took 14 seconds and often hit
  the request timeout. The appointments table had 40 million rows.
- **What Alex did:** he ran `EXPLAIN ANALYZE` on the query generated by the Django ORM and
  found a sequential scan. The filter was on clinic and date range. He added a composite index
  on `(clinic_id, scheduled_at)`, created with `CREATE INDEX CONCURRENTLY` through a Django
  migration (`AddIndexConcurrently`) so the table was not locked for writes. He also replaced a
  Python loop that counted rows with an ORM `annotate` and `aggregate`, so PostgreSQL did the
  counting.
- **Technologies:** Django ORM, PostgreSQL, EXPLAIN ANALYZE.
- **Result:** the report went from 14 seconds to 180 ms. No more report timeouts.

**EN (spoken):** "At Fabrikam Health, a monthly report took 14 seconds on a table with 40
million rows. I ran EXPLAIN ANALYZE and saw a sequential scan. I added a composite index on
clinic ID and scheduled date, created concurrently so we didn't lock writes, and I moved the
counting from a Python loop into the ORM aggregate. It went from 14 seconds to 180
milliseconds."

## Duplicate reminder incident

- **Company:** Fabrikam Health (2021).
- **Keywords:** duplicate reminders, reminder incident, acks_late
- **Problem:** appointment reminders were sent by SMS from Celery workers with a Redis broker.
  Alex enabled `acks_late` to avoid losing tasks when a worker crashed. But one batch task
  sent all reminders of a clinic and ran longer than the Redis broker visibility timeout, so
  the broker delivered the task again to another worker. 3,000 patients received the same
  reminder twice. The team only found out 2 hours later, from support tickets.
- **What Alex did:** it was his change, and he said so in the incident channel. He stopped the
  workers, wrote the postmortem and led the fix: one small task per reminder instead of one
  batch task, and a check against a `reminder_sent` record with a unique constraint per
  appointment before sending. He also added structured JSON logs with a correlation ID per
  appointment, Sentry for task errors and an alert on task retry rate.
- **Technologies:** Celery, Redis, PostgreSQL, Sentry, structured logging.
- **Result:** no duplicate reminders after the fix. A similar retry spike later in 2021 was
  detected by the alert in 5 minutes, instead of 2 hours.

**EN (spoken):** "At Fabrikam Health, I enabled acks late in Celery, but a long batch task ran
past the Redis visibility timeout and was delivered twice. 3,000 patients got the same SMS
twice, and we only saw it 2 hours later from support tickets. It was my change, and I said so.
I wrote the postmortem, split the batch into one task per reminder, added a unique sent
record, structured logs and a retry alert. The next spike was caught in 5 minutes."

## CI pipeline speed-up

- **Company:** Contoso Logistics (2022–2023).
- **Keywords:** CI pipeline, test suite, pytest-xdist
- **Problem:** the test suite took 35 minutes in CI and used a shared staging database, so
  tests were flaky (about 15 flaky failures per week). The team deployed once a week because
  each run was slow and unreliable.
- **What Alex did:** he split the suite into unit and integration tests, ran them in parallel
  with pytest-xdist, and replaced the shared database with a PostgreSQL service container in
  GitHub Actions, one fresh database per job. He added factory_boy factories instead of shared
  fixtures data, cached pip dependencies, and added a coverage gate with pytest-cov. The
  pipeline builds a Docker image and does a rolling deploy to ECS after the tests pass.
- **Technologies:** pytest, pytest-xdist, pytest-cov, factory_boy, GitHub Actions, Docker, ECS.
- **Result:** CI went from 35 minutes to 8 minutes. Flaky failures went from 15 per week to 1.
  Coverage went from 58% to 85%. The team moved from weekly to daily deploys.

**EN (spoken):** "At Contoso Logistics, our CI took 35 minutes and used a shared staging
database, so tests were flaky. I split unit and integration tests, ran them in parallel with
pytest-xdist, and gave each job its own Postgres container in GitHub Actions. CI went from 35
to 8 minutes, flaky failures from 15 a week to 1, and we moved from weekly to daily deploys."

## Nightly sales ETL

- **Company:** Tailspin Analytics (2019).
- **Keywords:** sales ETL, Airflow DAG, chunksize
- **Problem:** a nightly sales ETL written in pandas ran from cron as one big script. It took 6
  hours, sometimes ran out of memory on a 16 GB machine, and any failure meant running
  everything again.
- **What Alex did:** he moved it to an Airflow DAG with one task per region, so a failed region
  could be retried alone. He read the files in chunks (`chunksize`), used categorical dtypes
  for repeated text columns, and pushed the heavy aggregations into PostgreSQL instead of
  doing them in pandas.
- **Technologies:** pandas, Apache Airflow, PostgreSQL.
- **Result:** run time went from 6 hours to 50 minutes. Peak memory went from 14 GB to 3 GB.
  Failures are retried per region instead of rerunning the whole job.

**EN (spoken):** "At Tailspin Analytics, a nightly pandas ETL took 6 hours and sometimes ran
out of memory. I moved it to Airflow with one task per region, read the files in chunks, used
categorical types, and pushed the heavy aggregations into Postgres. It went from 6 hours to 50
minutes, and peak memory from 14 to 3 gigabytes."
