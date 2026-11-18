# Testing and CI/CD — study sheet

## Strategy

- Testing pyramid: many fast unit tests, fewer integration tests (real database, real queue
  emulation), a few end-to-end tests of the critical flows.
- Test behavior, not implementation details. One reason to fail per test.
- For backends, integration tests against a real PostgreSQL catch what mocks hide (constraints,
  transactions, SQL errors). Mock only external services you do not own.
- Every bug fix gets a regression test.

## pytest

- Fixtures (`@pytest.fixture`) provide setup and teardown; scopes: function (default), class,
  module, package, session. Shared fixtures go in `conftest.py`.
- `yield` fixtures run cleanup after the test.
- `@pytest.mark.parametrize` runs one test with many inputs.
- `monkeypatch` changes env vars, attributes and dict items for one test.
- Markers (`@pytest.mark.integration`) select or skip groups: `pytest -m "not integration"`.
- `pytest.raises` asserts exceptions.
- Plugins: pytest-xdist (`-n auto` runs tests in parallel processes), pytest-cov (coverage,
  `--cov-fail-under` gate), pytest-asyncio or anyio for async tests.
- `unittest.mock` (`patch`, `MagicMock`, `AsyncMock`) for test doubles.
- factory_boy builds test data; Hypothesis does property-based testing.

## Flaky tests

- Common causes: shared state (shared database, global variables), test order, time and
  timezones, network calls, race conditions in async code.
- Fixes: isolated database per worker or per test transaction, freeze time, remove network,
  deterministic data, run with random order to expose hidden dependencies.

## CI/CD with GitHub Actions

- Workflows are YAML files in `.github/workflows/`; triggers like `push`, `pull_request`.
- Jobs run in parallel by default; `needs:` creates dependencies; `strategy.matrix` tests several
  Python versions.
- Service containers (for example, `postgres`) give each job a fresh database.
- `actions/cache` (or the cache option of `actions/setup-python`) caches dependencies.
- Secrets in repository or environment secrets; prefer OIDC to assume a cloud role instead of
  long-lived keys.
- Environments with required reviewers protect production deploys.
- Typical pipeline: lint (ruff) → type check → unit tests → integration tests → build Docker
  image → push → deploy to staging → smoke test → deploy to production.

## Deploy safety

- Small, frequent deploys; feature flags for risky changes.
- Rolling or blue/green deploys with health checks; quick rollback to the previous image.
- Database migrations backward compatible (expand, migrate, contract).

## Likely interview questions

1. What is your testing strategy for a backend service?
2. Unit vs integration tests — how do you balance them?
3. How do you deal with flaky tests?
4. How do you test code that calls external APIs?
5. Describe your CI/CD pipeline.
6. How do you make a slow test suite faster?
7. How do you deploy database migrations safely?
