# Ready answers

## Tell me about yourself
I'm Alex Morgan, a backend engineer with 8 years of Python. Today I'm a Senior Backend Engineer at Contoso Logistics, where I build our shipment tracking platform with FastAPI, PostgreSQL, Redis and AWS. I rebuilt our carrier webhook intake as an event pipeline with SQS and Lambda. It handles 2 million events per day with zero duplicate updates. Before that, I worked with Django and Celery at Fabrikam Health, and with pandas and Airflow at Tailspin Analytics. I love reliable systems, and that's why payments interests me.
Tip: keep it under 40 seconds and stop. Let the interviewer pick what to dig into.

## Why are you leaving your current job?
I'm not leaving because of a problem. I've been at Contoso Logistics since 2022, and the tracking platform I helped build is stable now. The team is in good shape too. I want my next challenge to be in a domain where correctness matters even more, and payments is exactly that. Northwind Pay works on the problems I enjoy most: idempotency, retries and reliable event processing. So for me this is a step forward, not an escape.
Tip: never criticize Contoso Logistics.

## Why do you want to work at Northwind Pay?
Three reasons. First, the domain. In payments, a duplicate or a lost event is real money, and that's the kind of problem I like to solve. Second, the stack. You use FastAPI, PostgreSQL, Redis and AWS, which is what I use every day. Third, the work itself. You're moving merchant webhooks to an event-driven service, and I built a very similar pipeline with SQS and Lambda at Contoso Logistics. I can help there from day one.

## What are your strengths?
My main strength is that I measure before I change things. When something is slow or broken, I profile it, read the query plan or the logs, and fix the real cause. A second strength is ownership. When something I built fails, I say so, fix it, and add the test or the alert so it doesn't happen again. And I like to make the whole team faster, for example by improving CI and giving clear, kind code reviews.

## What is your biggest weakness?
I used to take the hardest bugs myself instead of sharing them. It felt faster, but it created knowledge silos in the team. Now, when I pick up a hard problem, I pair with someone or write a short note in the ticket, so the team learns with me. Today I mentor two mid-level engineers, so sharing what I know is part of my job.

## Tell me about a conflict or a disagreement with a colleague
At Contoso Logistics, our tracking API had a p95 of 900 milliseconds, and the tech lead wanted to rewrite it in Go. I disagreed, but I didn't want a fight. I asked for one week of profiling first, so we could decide with data, and he agreed. We found an N+1 problem, 12 queries per request. I fixed it and added a Redis cache. The p95 went to 120 milliseconds, he reviewed the results, and we dropped the rewrite.

## Tell me about a failure or a mistake you made
At Fabrikam Health, I enabled acks late in Celery, but a long batch task ran past the Redis visibility timeout and was delivered twice. 3,000 patients got the same SMS reminder twice, and we only saw it 2 hours later. It was my change, and I said so. I wrote the postmortem, split the batch into one task per reminder, and added a unique sent record, structured logs and a retry alert. The next spike was caught in 5 minutes.
Tip: say "it was my change" calmly. Ownership is the point of this story.

## When do you use asyncio, threads or multiprocessing?
The simple rule is: what is the code waiting for? If it waits on I/O, like HTTP calls or the database, I use asyncio when the libraries are async, because one thread can handle many waits. If the library is blocking, I use threads, because the GIL is released while they wait. If the work is CPU-bound, I use multiprocessing, because each process has its own GIL. And I never put blocking calls inside an async function.

## What is the GIL?
The GIL is a lock in CPython that lets only one thread run Python bytecode at a time. So threads don't speed up CPU-bound Python code, but they still work well for I/O, because the GIL is released while a thread waits. For CPU work, I use processes, or push the heavy part to NumPy or the database. And the GIL doesn't make code thread-safe, so shared state still needs a lock. Python 3.13 added an experimental build without it.

## How would you scale an API?
First I measure, so I know if the bottleneck is the code, the database or something else. Then the simple steps: keep the API stateless and add instances behind the load balancer, fix slow queries and N+1 problems, use connection pooling, and cache hot reads in Redis. Slow work goes to a queue. At Contoso Logistics, fixing an N+1 problem and adding a Redis cache took our tracking API from 900 to 120 milliseconds at p95.

## What is your caching strategy?
My default is cache-aside with Redis. The app reads the cache first. On a miss, it reads the database and writes the result with a TTL. The hard part is invalidation, so I combine a short TTL with deleting the key when the data changes. At Contoso Logistics, I cached the shipment summary for 30 seconds and invalidated it on every status-change event. And I never use the cache as the source of truth for money or balances.

## How do you fix a slow database query?
First I find the query, with pg_stat_statements or the slow query log. Then I run EXPLAIN ANALYZE to see the real plan. Usually it's a sequential scan, a missing index or stale statistics. At Fabrikam Health, a monthly report took 14 seconds on a table with 40 million rows. I added a composite index on clinic ID and scheduled date, created concurrently so writes weren't blocked. The report went from 14 seconds to 180 milliseconds.

## How do you make an operation idempotent?
An operation is idempotent when doing it twice has the same effect as doing it once. Retries always happen, so I assume duplicates. For APIs, the client sends an idempotency key, and the server stores it with the result under a unique constraint. For consumers, I store the event ID with a unique constraint, in the same transaction as the change. At Contoso Logistics, that's how our SQS pipeline handles 2 million events per day with zero duplicate updates.

## What is your testing strategy?
I follow the testing pyramid. Many fast unit tests for business rules, then integration tests against a real Postgres, because mocks hide constraint and transaction bugs. Only a few end-to-end tests for the critical flows. I mock only external services we don't own, and every bug fix gets a regression test. At Contoso Logistics, I gave each CI job its own Postgres container and added a coverage gate. Coverage went from 58% to 85%.

## Describe your CI/CD pipeline
Every pull request runs lint, unit tests and integration tests in GitHub Actions. The main branch builds a Docker image and does a rolling deploy to ECS. At Contoso Logistics, our CI took 35 minutes with a shared staging database, so tests were flaky. I ran tests in parallel with pytest-xdist and gave each job its own Postgres container. CI went to 8 minutes, flaky failures from 15 a week to 1, and we moved to daily deploys.

## How do you approach observability and monitoring?
I start with structured JSON logs with a correlation ID, so I can follow one request or one job from end to end. Then metrics for rate, errors and latency, plus queue age. I alert on what users feel, not on every CPU spike. At Fabrikam Health, we found a duplicate SMS problem 2 hours late, from support tickets. I added structured logs, Sentry and a retry-rate alert, and the next spike was caught in 5 minutes.

## How would you design a payment webhook system?
I'd keep the intake simple. The endpoint checks the signature, stores the raw event, puts it on a queue like SQS, and returns a 2xx response fast. Consumers process each event idempotently, using the event ID with a unique constraint. Failures retry with backoff, and after a few attempts they go to a dead-letter queue with an alarm. I built a similar intake at Contoso Logistics for carrier webhooks. Timeouts went from 4% to 0.1%, with zero duplicates.
Tip: if they push for more, talk about the transactional outbox for outgoing merchant webhooks.

## Do you have Kubernetes experience?
Honestly, my Kubernetes experience is basic. I deployed services with Helm charts that another team maintained, and I debug pods with kubectl logs and describe. I never designed or operated a cluster. Where I have strong production experience is ECS on Fargate: services behind a load balancer, rolling deploys with health checks, and auto scaling. The concepts are similar, so I'm confident I can ramp up on Kubernetes if the team needs it.

## Have you worked with Kafka?
I haven't used Kafka in production. My messaging experience is with SQS. At Contoso Logistics, I built an event pipeline with SQS and Lambda that handles 2 million events per day. I know the main ideas behind Kafka, like topics, partitions and consumer groups. And the same principles apply: at-least-once delivery, idempotent consumers and a plan for messages that keep failing. So I'd need to learn the tooling, but the design thinking is the same.

## Do you have payments or fintech experience?
Not directly, I haven't worked at a payments company. But I've spent years on the problems payments depends on. At Contoso Logistics, I built an event pipeline with SQS and Lambda where every consumer is idempotent, and it handles 2 million events per day with zero duplicate updates. In payments, that same discipline protects money instead of shipment statuses. I'm excited to learn the domain itself, like ledgers and reconciliation, from your team.

## What are your salary expectations?
I'd like to understand the full scope of the role and the whole package first, so I can give you a fair number. I'm flexible, and I'm confident we can find a range that works for both sides if this is the right fit. Could you share the range you have budgeted for this position? That would help me a lot to align my expectations with yours.
Tip: never say a number first in the technical rounds.

## Do you have any questions for us?
Yes, a few. First, how do you handle idempotency today, for the public API and for internal events? Second, how is the move of merchant webhooks to an event-driven service going, and where would I help first? Third, what does on-call look like, and what was the last incident the team learned from? And finally, what does success look like for this role in the first 90 days?
