# PostgreSQL — study sheet

## Indexes

- Default index type is B-tree: equality and range (`=`, `<`, `>`, `BETWEEN`, `ORDER BY`).
- Other types: GIN (arrays, JSONB, full-text search), GiST (geometric, ranges), BRIN (very
  large tables where values follow physical order, like append-only timestamps), Hash (equality).
- Composite index `(a, b)`: useful for filters on `a`, or on `a` and `b`; usually not for `b`
  alone (leftmost-column rule). Put the equality column first, the range column after.
- Partial index: `CREATE INDEX ... WHERE status = 'pending'` — small and fast for hot subsets.
- Covering index: `INCLUDE (col)` lets index-only scans return extra columns.
- Expression index: `CREATE INDEX ON users (lower(email))`.
- `CREATE INDEX CONCURRENTLY` builds without blocking writes; it is slower and cannot run inside
  a transaction block.
- Indexes cost: slower writes and more storage. Remove unused ones (`pg_stat_user_indexes`).

## Finding a slow query

1. Find it: `pg_stat_statements` (total and mean time), slow query log
   (`log_min_duration_statement`), APM traces.
2. `EXPLAIN` shows the plan; `EXPLAIN ANALYZE` runs the query and shows real times and rows
   (careful with writes — wrap in a transaction and roll back). `BUFFERS` adds I/O detail.
3. Look for: sequential scans on large tables with selective filters, big differences between
   estimated and actual rows (stale statistics → `ANALYZE`), sorts spilling to disk, nested loops
   over many rows.
4. Fix: add or change an index, rewrite the query, avoid functions on indexed columns, paginate
   with keyset (`WHERE id > last_id`) instead of large `OFFSET`.

## Transactions and concurrency

- MVCC: readers do not block writers and writers do not block readers; old row versions are
  cleaned by VACUUM (autovacuum).
- Default isolation level is Read Committed. Also Repeatable Read and Serializable (may raise
  serialization failures that the app must retry).
- `SELECT ... FOR UPDATE` locks rows; `FOR UPDATE SKIP LOCKED` is a common pattern for job
  queues in a table.
- Keep transactions short; long transactions hold locks and stop VACUUM from cleaning.
- Upsert: `INSERT ... ON CONFLICT (key) DO NOTHING | DO UPDATE` — the base of idempotent writes
  with a unique constraint.

## Operations

- Connection pooling (PgBouncer or the app's pool): Postgres uses one process per connection, so
  thousands of direct connections are expensive.
- Read replicas for read-heavy traffic (replication lag means reads may be slightly stale).
- Partitioning (declarative, by range or list) for very large tables such as events by month.
- JSONB for flexible attributes; index with GIN when you query inside it.
- Constraints (`UNIQUE`, `CHECK`, foreign keys) protect data even when the app has bugs.

## Likely interview questions

1. A query is slow. What do you do?
2. How does a composite index work? Does column order matter?
3. When would you use a partial index or a GIN index?
4. What is MVCC? Why does VACUUM exist?
5. How do you add an index to a big production table safely?
6. How do you implement an idempotent insert?
7. What isolation level does Postgres use by default?
8. OFFSET pagination vs keyset pagination?
