# Workflows

## Register a database

Use catalog SQL to check existing registrations. Resolve ambiguous names before writing. Create a `databases` record through REST with a descriptive name and the PocketContext server's base URL. Store its ID for ingestion. Credentials belong in the environment, not the registration. Update the same registration when its source moves.

## Synchronize metadata

Set `METACONTEXT_URL`, `METACONTEXT_TOKEN`, and `SOURCE_TOKEN`, then run `python3 ingestion/sync.py --database <id>`. The catalog token and source token authenticate independently. Read the JSON summary and inspect the ingestion run if it failed.

A running record prevents overlapping imports for the same database. After a crash, stop the old process before marking its run failed through REST. Include a UTC `finished_at` and an explanation in `error`, then retry. Do not infer absence from a failed run. Writes are incremental, so a failed run can have changed some records.

## Discover and document

Use SQL joins across databases, tables, and columns. Filter both tables and columns to `state = 'present'` for the currently observed inventory. Inspect the latest run to assess freshness; a present record alone does not prove the most recent scan succeeded.

Resolve record IDs through SQL before patching curated descriptions through REST. Ingestion leaves those descriptions intact. Do not edit identity or observation fields as a documentation operation.

## Explain missing objects

Inspect the source's current schema exposure and the latest successful run. An object may be missing because it was renamed, deleted, or removed from the server's exposed schema. Report that uncertainty. Do not call it physically deleted based only on the catalog.
