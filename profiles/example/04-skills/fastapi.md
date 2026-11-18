# FastAPI — study sheet

## Core ideas

- FastAPI is built on Starlette (the ASGI web layer) and Pydantic (validation). It runs on an
  ASGI server such as Uvicorn.
- Request and response models are Pydantic models; type hints drive validation, serialization
  and the automatic OpenAPI schema. Interactive docs at `/docs` (Swagger UI) and `/redoc`.
- `response_model` filters and documents the output (for example, hide internal fields).

## async def vs def

- `async def` endpoints run on the event loop. Use them when you `await` async libraries
  (async DB driver, httpx.AsyncClient).
- Plain `def` endpoints run in a thread pool, so blocking code there does not freeze the loop.
- The common bug: blocking calls (requests, a sync DB driver, `time.sleep`) inside an
  `async def` endpoint. That blocks every request on that worker.

## Dependency injection

- `Depends()` declares dependencies: DB session, current user, settings, pagination.
- Dependencies with `yield` run cleanup after the response (for example, closing the DB session).
- Easy to override in tests with `app.dependency_overrides`.

## Other features

- `BackgroundTasks` run after the response, in the same process. Fine for small things (send a
  log, a quick email); for reliable or heavy work use a queue (SQS, Celery).
- Lifespan handler (`lifespan=` on the app) for start-up and shutdown (connection pools, clients).
- `HTTPException` and custom exception handlers; validation errors return 422 by default.
- Middleware for cross-cutting concerns (correlation ID, timing, CORS).
- Security utilities: OAuth2 with password flow and bearer tokens, API key headers.

## Production

- Run several worker processes (Uvicorn workers, for example under Gunicorn, or one process per
  container and scale containers).
- Use connection pooling for the database and reuse HTTP clients.
- Health check endpoint for the load balancer.
- Return 202 Accepted for work that is queued and processed later.

## Testing

- `TestClient` (based on httpx) calls the app in-process, no server needed.
- Override dependencies to use a test database or a fake user.
- For async tests, `httpx.AsyncClient` with the ASGI transport and an async test plugin.

## Likely interview questions

1. Why FastAPI over Flask or Django?
2. What is the difference between `async def` and `def` endpoints?
3. How does dependency injection work in FastAPI?
4. When would you use `BackgroundTasks` and when a queue?
5. How do you test a FastAPI app?
6. How do you handle validation errors and custom errors?
7. How do you make a FastAPI service fast under load?
