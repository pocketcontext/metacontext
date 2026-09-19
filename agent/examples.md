# Examples

Send SQL to `POST /api/context/query` on MetaContext, authenticated with its agent token:

```json
{"sql":"SELECT id, name, endpoint FROM databases ORDER BY name, id"}
```

Responses contain `columns`, positional `rows`, and `truncated`. Never treat a truncated response as a complete inventory. Narrow queries or paginate with stable ordering.

Find exposed tables and columns:

```sql
SELECT d.name AS database_name, t.name AS table_name,
       c.name AS column_name, c.data_type, c.description
FROM databases d
JOIN tables t ON t.database = d.id
JOIN columns c ON c."table" = t.id
WHERE t.state = 'present' AND c.state = 'present'
ORDER BY d.id, t.name, c.name
LIMIT 100
```

Find undocumented tables:

```sql
SELECT t.id, d.name AS database_name, t.name AS table_name
FROM tables t
JOIN databases d ON d.id = t.database
WHERE t.state = 'present' AND t.description = ''
ORDER BY d.id, t.name
LIMIT 100
```

Inspect recent runs:

```sql
SELECT id, database, status, created, finished_at, error
FROM ingestion_runs
ORDER BY created DESC, id DESC
LIMIT 20
```

After resolving a table ID, send `PATCH /api/collections/tables/records/<id>` with the catalog agent token:

```json
{"description":"Sales opportunities tracked by the CRM."}
```

To recover an abandoned run, first stop its worker. Then send `PATCH /api/collections/ingestion_runs/records/<run-id>` with the actual UTC completion time:

```json
{
  "status": "failed",
  "finished_at": "2026-09-19 12:00:00.000Z",
  "error": "Worker stopped after interruption; retry required."
}
```

Source discovery uses only `GET /api/context/schema` on the registered source endpoint, authenticated with its source agent token. Never query source SQLite metadata or application rows to supplement this connector.
