# Python — advanced study sheet

> Conservative facts about CPython. When in doubt, the official docs in `07-official-docs/` win.

## GIL (Global Interpreter Lock)

- In CPython, the GIL lets only one thread execute Python bytecode at a time, in one process.
- Threads still help for I/O-bound work: the GIL is released while a thread waits on blocking
  I/O (sockets, files, `time.sleep`), and many C extensions release it during long computations
  (for example, parts of NumPy and hashlib).
- CPU-bound pure-Python code does not get faster with threads. Use `multiprocessing` or
  `concurrent.futures.ProcessPoolExecutor` (separate processes, each with its own GIL), or move
  the hot loop to C, NumPy or the database.
- The GIL does not make your code thread-safe. Operations like `counter += 1` are several
  bytecodes, so shared state still needs a `threading.Lock`.
- Python 3.13 added an optional, experimental free-threaded build without the GIL (PEP 703).
  The default build still has the GIL.

## asyncio vs threads vs multiprocessing

| | asyncio | threads | multiprocessing |
|---|---|---|---|
| Best for | many concurrent I/O waits (HTTP calls, DB, sockets) | blocking I/O with libraries that are not async | CPU-bound work |
| Concurrency model | cooperative, one thread, event loop; switches only at `await` | preemptive, OS threads, share memory | separate processes, no shared memory by default |
| Cost | very cheap tasks | more memory per thread | process start-up and pickling data between processes |
| Main risk | one blocking call freezes the whole loop | race conditions | serialization overhead |

- `asyncio.gather()` runs awaitables concurrently; `asyncio.TaskGroup` (3.11+) is structured
  concurrency: if one task fails, the others are cancelled.
- Never call blocking code inside `async def`. Use `await asyncio.to_thread(func)` (3.9+) or
  `loop.run_in_executor()`.
- `asyncio.Semaphore` limits concurrency (for example, max 10 calls to a partner API).
- Timeouts: `asyncio.timeout()` (3.11+) or `asyncio.wait_for()`.

## Typing

- Type hints are not enforced at runtime; tools like mypy or pyright check them.
- Useful constructs: `list[int]` and `X | None` (3.10+ syntax), `TypedDict`, `Protocol`
  (structural typing, "duck typing with types"), `Generic`/`TypeVar`, `Literal`, `Final`.
- Pydantic and FastAPI do read type hints at runtime to validate data.

## dataclasses vs Pydantic

- `@dataclass` generates `__init__`, `__repr__` and `__eq__`. Options: `frozen=True`
  (immutable), `slots=True` (3.10+, less memory). No validation of types.
- Pydantic models validate and convert input data (parsing JSON, coercing types) and produce
  clear errors. Pydantic v2 has its core written in Rust (pydantic-core).
- Rule of thumb: Pydantic at the edges (API input, config, external data); dataclasses for
  internal domain objects.

## Generators and iterators

- A function with `yield` returns a generator: values are produced lazily, one at a time.
  Good for large files or streams because memory stays constant.
- Generator expressions: `sum(x * x for x in rows)` — no intermediate list.
- `yield from` delegates to another iterable.
- `itertools` (`islice`, `chain`, `groupby`) works on iterators without loading everything.

## Context managers

- `with` guarantees cleanup: `__enter__` and `__exit__` run even when an exception happens.
- `contextlib.contextmanager` turns a generator into a context manager (code before `yield` is
  setup, code after is cleanup, inside `try/finally`).
- Async version: `async with`, `__aenter__`/`__aexit__`, `contextlib.asynccontextmanager`.
- Typical uses: DB transactions, locks, temporary files, timers.

## Decorators, closures, other language points

- A decorator is a function that takes a function and returns a new one; use
  `functools.wraps` to keep the name and docstring. `functools.lru_cache` / `cache` memoize.
- Mutable default arguments (`def f(x=[])`) are shared between calls — use `None`.
- `is` compares identity, `==` compares value.
- `__slots__` reduces per-instance memory.

## Packaging and environments

- `pyproject.toml` is the standard place for project metadata (PEP 621) and build settings.
- A wheel (`.whl`) is a built package; sdist is the source distribution.
- Use a virtual environment per project (`python -m venv .venv`).
- Pin runtime dependencies for applications (lock file or pinned requirements); use version
  ranges for libraries.

## Performance profiling

- Measure first. `cProfile` + `pstats` for deterministic profiling of a script; `timeit` for
  micro-benchmarks.
- `py-spy` is a sampling profiler that can attach to a running process without changing code
  (good for production).
- Typical wins: fix N+1 queries, push work to the database, cache, avoid repeated work in
  loops, use built-ins and comprehensions, vectorize with NumPy/pandas.

## Memory

- CPython frees most objects by reference counting; a cyclic garbage collector (`gc` module)
  handles reference cycles.
- `tracemalloc` shows where memory is allocated and lets you compare snapshots to find leaks.
- Common leaks: unbounded caches or global dicts, references kept in closures, large objects in
  long-lived lists.
- For big data: generators, chunked reads, `__slots__`, smaller dtypes in pandas.

## Likely interview questions

1. What is the GIL and when does it matter?
2. asyncio vs threads vs multiprocessing — when do you use each?
3. What happens if you call a blocking function inside an async endpoint?
4. Dataclasses vs Pydantic models?
5. How do generators save memory?
6. How do you write a context manager?
7. How do you find a performance problem in a Python service?
8. How do you investigate a memory leak?
9. Is Python code thread-safe because of the GIL?
10. How do you package and pin dependencies for a service?
