# MetaContext

Read `README.md`, `agent/schema.md`, `agent/workflows.md`, and `agent/examples.md` before catalog data operations.

MetaContext owns the catalog schema, ingestion pipeline, configuration, and agent workflows. PocketContext supplies the application-independent server. Preserve that repository boundary.

Read catalog data through authenticated PocketContext schema and SQL endpoints. Read source metadata only through `GET /api/context/schema`; do not read source application rows or access SQLite directly. Write catalog records only through PocketBase's records API. Migrations define schema; they are not a way to edit catalog records.

Use agent credentials for ordinary operations and superuser access for provisioning and maintenance. Keep tokens, passwords, and `pb_data/` out of Git and logs. The catalog is a shared workspace: SQL does not apply per-record API rules.

A database registration is persistent identity. Its endpoint may change without creating a new registration. Table names are unique within a database; column names are unique within a table. Renames appear as missing and new objects. `missing` means absent from the source's exposed schema, not proven physical deletion.

Descriptions are curated. Ingestion must not overwrite them. Only finalize missing-object reconciliation after a complete successful schema scan. Preserve retry safety after partial writes. Stop an interrupted worker before marking its running ingestion record failed through REST and retrying.

Before editing, inspect Git status and preserve user changes. Run unit tests and `python3 tests/integration.py --binary ../pocketcontext/bin/pocketcontext` after implementation changes. Keep `POCKETCONTEXT_VERSION` aligned with the tested server. Report changed repositories and checks performed.
