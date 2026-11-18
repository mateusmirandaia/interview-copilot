# Target job — Senior Python Backend Engineer at Northwind Pay

> Fictional company and job ad, used by the example profile.

## Job ad

**Northwind Pay** — Senior Python Backend Engineer (Remote, Americas; 4 hours overlap with US
Eastern time).

Northwind Pay is a payments platform for small and mid-size online merchants: card and bank
transfer payments, payouts and merchant webhooks.

What you will do:
- Build and run the services behind payments, payouts and merchant notifications.
- Design event-driven flows that are correct under retries, duplicates and partial failures.
- Improve reliability: testing, CI/CD, observability and incident response.
- Review code and mentor other engineers.

Requirements:
- 6+ years building backend systems in Python.
- Strong experience with FastAPI or Django, PostgreSQL and Redis.
- Experience with AWS (Lambda, SQS, ECS or similar).
- Solid testing practice with pytest and CI/CD pipelines.
- Good written and spoken English.

Nice to have:
- Payments or fintech experience.
- Kafka or other streaming platforms.
- Kubernetes.
- Data pipelines (Airflow).

## Company notes

- Stack (from the ad and the recruiter): FastAPI services, PostgreSQL, Redis, AWS (SQS, Lambda,
  ECS), GitHub Actions.
- Their engineering blog talks about idempotency keys on their public API and a ledger service.
- They are moving merchant webhooks from a cron job to an event-driven service.
- Alex has no payments experience: be honest, and connect it to correctness work he did
  (idempotent event pipeline, duplicate reminder incident).

## Interview process

1. Recruiter screen (done).
2. Technical interview with a Staff Engineer — 60 minutes, scenario and design questions.
3. Engineering manager interview — behavioral.

## Interviewer notes

- **Daniel Reyes — Staff Engineer (fictional).** Leads the payments core team. Likes concrete
  numbers and "what happens if this fails?" follow-ups. Expect questions on idempotency,
  retries, transactions and how to test them.
- **Priya Shah — Engineering Manager (fictional).** Behavioral round: ownership, conflict,
  mistakes, mentoring, working remotely across time zones.

## Questions to ask them

1. How do you handle idempotency today for the public API and for internal events?
2. What does the on-call rotation look like, and what was the last incident you learned from?
3. How is the move of merchant webhooks to an event-driven service going? Where would I help first?
4. How do you split work between the payments core team and the other teams?
5. What does success look like for this role in the first 90 days?
