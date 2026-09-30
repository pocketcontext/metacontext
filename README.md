# MetaContext

A relational metadata catalog operated through a coding agent. MetaContext ingests the application schema exposed by a [PocketContext](https://github.com/pocketcontext/pocketcontext) server and stores database, table, and column metadata in a separate PocketBase database. Agents query the catalog with SQL; ingestion and agent edits use PocketBase's records API.

The first connector targets SQLite `main` through `GET /api/context/schema`. It collects exposed table names, column names, and SQL types. It does not read source application rows or open the source SQLite file. Auth collections, internal tables, and unexposed fields remain outside the catalog. This is a catalog of the exposed schema, not the full physical database. It does not collect indexes, constraints, PocketBase field semantics, views, or lineage.

## Run locally

Keep `metacontext` and `pocketcontext` in sibling directories. Use the Go version in PocketContext's `go.mod`, with CGO enabled and a C compiler. Build the server at the compatible commit recorded in `POCKETCONTEXT_VERSION`:

```sh
cd ../pocketcontext
git checkout "$(cat ../metacontext/POCKETCONTEXT_VERSION)"
cd ../metacontext
make -C ../pocketcontext build
../pocketcontext/bin/pocketcontext serve --http=127.0.0.1:8091 \
  --dir=./pb_data --migrationsDir=./pb_migrations --hooksDir=./pb_hooks \
  --contextConfig=./pocketcontext.json
```

The server applies migrations on startup. Keep this data directory separate from DealContext or any other source application. No agent credentials or catalog records are seeded.

## Provision and ingest

Create a superuser with the server's `superuser upsert <email> <password>` command, using the same data directory and migration paths. Authenticate at `POST /api/collections/_superusers/auth-with-password`. With its token, create an agent at `POST /api/collections/agents/records`:

```json
{
  "name": "Catalog agent",
  "email": "catalog@example.com",
  "password": "<strong-password>",
  "passwordConfirm": "<same-strong-password>"
}
```

Authenticate that agent at `POST /api/collections/agents/auth-with-password` with `identity` and `password`. Use its token for catalog operations. Separately obtain an agent token accepted by the source server's schema endpoint. Superuser tokens cannot substitute for agent tokens on PocketContext SQL routes.

With the catalog agent token, register the source database through `POST /api/collections/databases/records`:

```json
{
  "name": "DealContext",
  "endpoint": "http://127.0.0.1:8090",
  "description": "Sales application schema"
}
```

Keep the returned record ID. Set `METACONTEXT_URL` to `http://127.0.0.1:8091`, `METACONTEXT_TOKEN` to the catalog agent token, and `SOURCE_TOKEN` to the source agent token in your environment. Keep credentials out of files, logs, and shell history. Then run:

```sh
python3 ingestion/sync.py --database <database-record-id>
```

The importer reads the registered endpoint and prints a JSON run summary. It never registers a database automatically. Updating the registration's endpoint preserves identity when the source moves; do not reuse that registration for a different database.

## Synchronization behavior

Tables are unique by database and name; columns are unique by table and name. Their PocketBase IDs survive repeated imports. SQLite supplies no durable object identity through this endpoint, so renames appear as missing objects and new objects. Reusing a name reuses the catalog identity.

Ingestion updates source-controlled metadata and observation markers. It leaves curated `description` fields unchanged. A successful complete scan marks unobserved objects `missing`. Missing means absent from the exposed schema; a configuration or permission change can cause it without a physical deletion. Failed scans must not be interpreted as complete inventories.

Only one ingestion run can be `running` per database. An interrupted process can leave a running record behind. Stop the old worker, inspect its run through catalog SQL, then mark it `failed` with `finished_at` and an explanatory `error` through the records API before retrying. Do not clear a live worker's run. A run uses multiple REST requests, so readers can see partial updates; retries reconcile existing records.

All catalog agents share visibility and access. SQL does not inherit per-record API rules. Database registrations contain nonsecret endpoints; credentials stay in the ingestion environment. See [schema](agent/schema.md), [workflows](agent/workflows.md), and [examples](agent/examples.md).

## Request tracing

The pinned server enables a bounded in-memory trace buffer for `metacontext`. Ordinary requests do not record traces unless the client sends `X-Context-Trace: 1`. SQL text additionally requires `X-Context-Capture-Sql: 1`; although the server permits SQL capture, the wrapper sends this only with explicit `--capture-sql`. Source servers must independently adopt compatible buffer configuration. No source rows are read by metadata ingestion.

Use the ObserveContext skill's multi-origin wrapper to measure both catalog SQL/REST and source schema HTTP requests under one owned operation. Configure and authenticate ObserveContext separately from `METACONTEXT_TOKEN` and `SOURCE_TOKEN`, then use the registered source's exact origin:

```sh
python3 /path/to/observecontext/scripts/oc.py capture \
  --service metacontext.ingestion --upload \
  --origin "metacontext.client=$METACONTEXT_URL" \
  --origin "source.metadata=https://source.example.com" \
  ingestion/sync.py --database <database-record-id>
```

`--origin` mappings are explicit allowlists, not wildcard discovery: the catalog and source have distinct client service labels and retain their own authentication. The wrapper retrieves each server trace only from that request's origin using its source token in memory. It refuses cross-origin credential forwarding and never includes the ObserveContext destination as a capture target. Authentication, browser, files, realtime and arbitrary non-API paths are outside capture scope.

Source buffers expire after 120 seconds and may lose telemetry on restart or capacity limits. Completed client/server pairs are persisted in ObserveContext's private account-bound local queue; retry delivery with `oc.py flush`. Capture preserves the ingestion command's exit status when telemetry delivery fails. Server tokens, REST payloads and results never enter the queue. See ObserveContext's instrumentation documentation for timing boundaries and retention limits.

## Verify

Use Python 3.12 or later. The integration test also needs a sibling DealContext checkout containing the commit in `DEALCONTEXT_TEST_VERSION`; it copies that committed fixture into a temporary directory and leaves the checkout untouched. Override its location with `--dealcontext /path/to/dealcontext`.

```sh
python3 -m unittest discover -s tests
python3 tests/integration.py --binary ../pocketcontext/bin/pocketcontext
```

The integration test uses isolated temporary databases. Restart the server after schema or SQL exposure changes. Keep `POCKETCONTEXT_VERSION` aligned with intentionally adopted server changes.

## Browser reader and permanent links

The authenticated reader at `/` provides a collection chooser, server-side text search,
paginated records, collection-specific filters, and outgoing/reverse relationship links.
Use `/#/<collection>/<record-id>` for a current-record permalink. Renames preserve this
identity; deletion or loss of access may make a link unavailable. Search/filter state is
stored in the hash query, and **Copy record link** omits that state. **Copy search link**
shares the current collection/filter view. Links do not grant access or preserve history.
The destination survives password sign-in and reload. MetaContext uses provisioned
agent accounts; no Google provider is configured by this reader.

Records are read through the existing authenticated SQL endpoint. The browser never
queries auth collections, writes business records, or acknowledges anything on opening.
Relationship labels use only authorized SQL; unavailable targets reveal no resolved
label. User-directory records contain display names only. Tokens are stored per tab in
session storage, cleared on sign-out; refresh on focus or the **Refresh** button reloads
current data. Markdown never executes HTML or loads remote images. Record metadata is
collapsed below business fields. Currency amounts retain their original minor-unit
values alongside formatted currency. No mixed-currency totals are calculated.

The reader's explicit navigation model lives in `ui/src/config.ts`. Keep its schema
snapshot aligned with the exported schema when changing columns; `tests/reader.py`
compares it with the real authenticated schema. The UI is built into the application
image; for local development build it before starting the ordinary server:

```sh
cd ui
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm e2e
cd ..
python3 tests/reader.py --binary /absolute/path/to/pinned/pocketcontext --browser
```

Use Node.js 24 and pnpm 10.33.2. The browser smoke uses synthetic records and an isolated
temporary database. It tests actual production assets, authentication, direct links,
reload, search pagination, mobile navigation, and SQL/schema compatibility. Unit and
mocked browser tests additionally cover query escaping, malformed routes, relationship
labels, and inert Markdown. Generated assets are not committed.
For browser Google OAuth, register the application's own
`https://<application-host>/api/oauth2-redirect` URI in its existing OAuth client.

MetaContext is code-ready only: no production hostname, deployment, or cloud resources are created. Its optional Dockerfile serves port 8080 with state mounted at `/storage`; deployment and backups require separate operator configuration.
