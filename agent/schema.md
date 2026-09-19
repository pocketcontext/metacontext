# Catalog schema

Every catalog record has a PocketBase `id`, `created`, and `updated`. Relation values are PocketBase record IDs. Authentication uses the `agents` collection, which is excluded from SQL.

| Collection | Fields |
|---|---|
| `databases` | `name`, `endpoint`, curated `description` |
| `tables` | `database` relation, `name`, curated `description`, `state`, `last_seen_run` |
| `columns` | `table` relation, `name`, source `data_type`, curated `description`, `state`, `last_seen_run` |
| `ingestion_runs` | `database` relation, `status`, `finished_at`, `error` |

`state` is `present` or `missing`. Run `status` is `running`, `succeeded`, or `failed`. `last_seen_run` records the observing run. Table identity is `(database, name)`; column identity is `(table, name)`. Unique indexes enforce these identities. Only one running ingestion record is allowed per database. Table and column identity fields cannot be changed after creation, and a run cannot change its database. An observation marker must refer to a run for the same database. These rules are enforced by server hooks. Agents can create and update catalog records; deletion requires superuser access.

The connector catalogs exposed tables in SQLite `main`; there is no separate schemas collection. `data_type` is the SQL type reported by PocketContext, not a complete PocketBase field definition. Missing objects remain in the catalog. Names reused upstream reuse catalog identities; renames do not preserve identity automatically.

Database endpoints contain no credentials. Changing an endpoint is appropriate only when the same logical source moves. All catalog collections are shared across agents.
