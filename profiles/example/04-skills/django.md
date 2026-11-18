# Django — study sheet

## ORM essentials

- QuerySets are lazy: no SQL runs until you iterate, slice, call `list()`, `len()`, etc.
- N+1 problem: one query for the list, then one per row for a related object.
  - `select_related()` — follows ForeignKey and OneToOne with a SQL JOIN (one query).
  - `prefetch_related()` — for ManyToMany and reverse ForeignKey; runs a separate query and joins
    in Python.
- `only()` / `defer()` load fewer columns; `values()` / `values_list()` return dicts or tuples.
- `annotate()` and `aggregate()` (`Count`, `Sum`, `Avg`) push computation to the database.
- `F()` expressions update fields in the database without a race (`stock=F("stock") - 1`);
  `Q()` objects build OR / complex filters.
- `bulk_create()` and `bulk_update()` for many rows; `iterator()` for large result sets.
- `django-debug-toolbar` or query logging to see the SQL; `QuerySet.explain()` shows the plan.

## Transactions and concurrency

- `transaction.atomic()` — a block that commits or rolls back as a unit. Nested blocks become
  savepoints.
- `select_for_update()` locks rows until the end of the transaction (must be inside `atomic`).
- `transaction.on_commit()` runs a callback only after a successful commit — use it to enqueue a
  Celery task so the worker never sees uncommitted data.

## Migrations

- `makemigrations` generates, `migrate` applies. Migrations are code: review them.
- For big tables: add nullable columns first, backfill in batches, then add constraints.
- On PostgreSQL, `AddIndexConcurrently` (from `django.contrib.postgres.operations`) creates an
  index without blocking writes; the migration must be non-atomic (`atomic = False`).

## Other topics

- Middleware: request/response hooks (auth, logging, correlation IDs).
- Signals: decoupled hooks (`post_save`); avoid hiding important business logic in them.
- Django REST Framework: serializers (validation), viewsets, routers, permissions, throttling,
  pagination.
- Async: async views are supported since Django 3.1, and the ORM has an async query interface
  since 4.1 (`aget()`, `acount()`, `async for`). Many projects still run sync under WSGI.
- Caching framework with Redis backend; `cache_page` for whole views.
- Security defaults: CSRF protection, ORM parameterizes queries (protects against SQL injection),
  template auto-escaping (XSS).

## Likely interview questions

1. What is the N+1 problem and how do you fix it in Django?
2. `select_related` vs `prefetch_related`?
3. How do you make a slow Django page fast?
4. How do you run a migration on a very large table without downtime?
5. How do you avoid race conditions when updating a counter?
6. Why use `transaction.on_commit()` with Celery?
7. Django vs FastAPI — when do you choose each?
