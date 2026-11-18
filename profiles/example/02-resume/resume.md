# Alex Morgan — Senior Python Backend Engineer

> Fictional candidate used as the example profile of Interview Copilot.
> All companies, people and numbers are invented.

- **Location:** Curitiba, Brazil. Remote. Works with US teams (overlap with US Eastern time).
- **Languages:** Portuguese (native), English (professional working proficiency).
- **Years of experience:** 8 years with Python (since 2018).

## Summary

Backend engineer focused on reliable APIs and event-driven systems in Python. Builds services
with FastAPI and Django on PostgreSQL and Redis, runs them on AWS (Lambda, SQS, ECS), and
cares about tests, CI/CD and observability. Some data engineering with pandas and Airflow.
Known for measuring before optimizing and for turning incidents into lasting fixes.

## Stack

- **Languages:** Python (advanced), SQL (advanced), Bash (basic).
- **Frameworks:** FastAPI, Django, Django REST Framework, SQLAlchemy, Pydantic, Celery.
- **Data stores:** PostgreSQL, Redis.
- **Cloud (AWS):** Lambda, SQS, ECS on Fargate, RDS for PostgreSQL, S3, CloudWatch, IAM,
  Secrets Manager.
- **Containers:** Docker (daily use), Kubernetes (basic usage only).
- **Testing and CI/CD:** pytest, pytest-xdist, pytest-cov, factory_boy, GitHub Actions.
- **Observability:** structured JSON logs, CloudWatch dashboards and alarms, Sentry.
- **Data engineering:** pandas, Apache Airflow.

## Experience

### Contoso Logistics — Senior Backend Engineer (Mar 2022 – present)

Shipment tracking platform for carriers and e-commerce customers.
- Rebuilt the carrier webhook intake as an event pipeline with SQS and Lambda, with
  idempotent processing (2 million events per day).
- Cut the p95 latency of the public tracking API from 900 ms to 120 ms with query fixes and
  a Redis cache.
- Reduced the CI pipeline from 35 minutes to 8 minutes and moved the team from weekly to
  daily deploys.
- Mentors two mid-level engineers; runs the backend code review guidelines.

### Fabrikam Health — Backend Engineer (Feb 2020 – Feb 2022)

Clinic scheduling software (Django monolith on PostgreSQL).
- Fixed the monthly appointment report: from 14 seconds to 180 ms with a composite index.
- Owned the SMS reminder service built on Celery and Redis; led the postmortem of a
  duplicate-reminder incident and added alerting.

### Tailspin Analytics — Python Developer (Jan 2018 – Jan 2020)

Retail sales analytics for mid-size store chains.
- Rewrote the nightly sales ETL with pandas and Airflow: from 6 hours to 50 minutes.
- Built internal Django admin tools and REST endpoints for the reporting team.

## Education

- BSc in Computer Science — Lakeside University (fictional), 2017.

## Certifications

- AWS Certified Developer – Associate (2023).

## What Alex does NOT do

- No Rust, Go or Java in production (reads Go code, never shipped it).
- No Kafka in production (uses SQS for messaging).
- Kubernetes: basic usage only — deploys with existing Helm charts, uses kubectl logs and
  describe. Never designed or operated a cluster.
- No machine learning model training.
- No frontend beyond simple Django templates.
