#!/usr/bin/env python3
"""Copy an exposed PocketContext schema into MetaContext through HTTP APIs."""
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


class SyncError(Exception):
    pass


class Truncated(SyncError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url, token=""):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise SyncError("Endpoint must be an HTTP(S) URL without credentials, query, or fragment")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        req = urllib.request.Request(self.base_url + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            # Do not include remote bodies or URLs: either can contain secrets.
            raise SyncError(f"{method} API request failed with HTTP {error.code}") from None
        except (OSError, ValueError):
            raise SyncError("API connection failed") from None
        if len(raw) > 16 * 1024 * 1024:
            raise SyncError("API response exceeded 16 MiB")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise SyncError("API returned invalid JSON") from None

    def query(self, sql):
        result = self.request("POST", "/api/context/query", {"sql": sql})
        if result.get("truncated"):
            raise Truncated("Catalog query was truncated")
        return [dict(zip(result["columns"], row)) for row in result["rows"]]

    def scan(self, collection, fields, where):
        """Keyset pagination, reducing the page size for server byte/row limits."""
        cursor, page_size = "", 100
        records = []
        while True:
            sql = (f'SELECT {fields} FROM "{collection}" WHERE ({where}) '
                   f'AND id > {literal(cursor)} ORDER BY id LIMIT {page_size}')
            try:
                page = self.query(sql)
            except Truncated:
                if page_size == 1:
                    raise
                page_size = max(1, page_size // 2)
                continue
            if not page:
                return records
            records.extend(page)
            cursor = page[-1]["id"]

    def create(self, collection, body):
        return self.request("POST", f"/api/collections/{collection}/records", body)

    def patch(self, collection, record_id, body):
        record_id = urllib.parse.quote(record_id, safe="")
        return self.request("PATCH", f"/api/collections/{collection}/records/{record_id}", body)


def literal(value):
    if not isinstance(value, str) or "\x00" in value:
        raise SyncError("Invalid SQL string")
    return "'" + value.replace("'", "''") + "'"


def validate_schema(payload):
    """Validate the entire observation before any catalog entity is changed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list):
        raise SyncError("Source schema must contain a tables array")
    if payload.get("truncated"):
        raise SyncError("Source schema is incomplete")
    names = set()
    for table in payload["tables"]:
        if not isinstance(table, dict):
            raise SyncError("Invalid source table")
        name = table.get("name")
        if not isinstance(name, str) or not name or len(name) > 1000 or "\x00" in name or name in names:
            raise SyncError("Invalid or duplicate source table name")
        names.add(name)
        if not isinstance(table.get("columns"), list):
            raise SyncError("Source table must contain a columns array")
        columns = set()
        for column in table["columns"]:
            if not isinstance(column, dict):
                raise SyncError("Invalid source column")
            name, data_type = column.get("name"), column.get("type")
            if (not isinstance(name, str) or not name or len(name) > 1000
                    or "\x00" in name or name in columns):
                raise SyncError("Invalid or duplicate source column name")
            if not isinstance(data_type, str) or len(data_type) > 1000 or "\x00" in data_type:
                raise SyncError("Invalid source column type")
            columns.add(name)
    return payload["tables"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")


def sync(catalog, database_id, source_token):
    databases = catalog.query(f"SELECT id, endpoint FROM databases WHERE id = {literal(database_id)}")
    if len(databases) != 1:
        raise SyncError("Database registration not found")
    source = Client(databases[0]["endpoint"], source_token)
    # A unique partial index rejects concurrent runs. Never automatically reclaim
    # a running record: the original process may still be writing.
    run = catalog.create("ingestion_runs", {"database": database_id, "status": "running"})
    run_id = run["id"]
    try:
        observed = validate_schema(source.request("GET", "/api/context/schema"))
        tables = catalog.scan("tables", "id, name, state", f"database = {literal(database_id)}")
        table_ids = f"SELECT id FROM tables WHERE database = {literal(database_id)}"
        columns = catalog.scan("columns", 'id, "table", name, state, data_type', f'"table" IN ({table_ids})')
        table_by_name = {row["name"]: row for row in tables}
        column_by_key = {(row["table"], row["name"]): row for row in columns}
        seen_tables, seen_columns = set(), set()
        for table in observed:
            body = {"state": "present", "last_seen_run": run_id}
            existing = table_by_name.get(table["name"])
            if existing:
                record = catalog.patch("tables", existing["id"], body)
            else:
                record = catalog.create("tables", dict(body, database=database_id, name=table["name"]))
            table_id = record["id"]
            seen_tables.add(table_id)
            for column in table["columns"]:
                body = {"state": "present", "last_seen_run": run_id, "data_type": column["type"]}
                existing = column_by_key.get((table_id, column["name"]))
                if existing:
                    record = catalog.patch("columns", existing["id"], body)
                else:
                    record = catalog.create("columns", dict(body, table=table_id, name=column["name"]))
                seen_columns.add(record["id"])
        # Only a complete validated schema and successful upserts reach this phase.
        # Missing means absent from the exposed schema, not necessarily deleted.
        for collection, previous, seen in [("columns", columns, seen_columns), ("tables", tables, seen_tables)]:
            for record in previous:
                if record["id"] not in seen and record["state"] != "missing":
                    catalog.patch(collection, record["id"], {"state": "missing"})
        catalog.patch("ingestion_runs", run_id, {"status": "succeeded", "finished_at": now()})
        return {"run": run_id, "database": database_id, "status": "succeeded",
                "tables": len(seen_tables), "columns": len(seen_columns)}
    except Exception:
        try:
            catalog.patch("ingestion_runs", run_id, {
                "status": "failed", "finished_at": now(),
                "error": "Ingestion failed; changes may be partial. Inspect the source and retry after resolving the failure.",
            })
        except Exception:
            pass  # Leave the running lock intact if the catalog is unavailable.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Existing MetaContext database record ID")
    args = parser.parse_args()
    try:
        client = Client(os.environ["METACONTEXT_URL"], os.environ["METACONTEXT_TOKEN"])
        print(json.dumps(sync(client, args.database, os.environ["SOURCE_TOKEN"])))
    except KeyError:
        parser.exit(1, "Set METACONTEXT_URL, METACONTEXT_TOKEN, and SOURCE_TOKEN.\n")
    except SyncError as error:
        parser.exit(1, f"Sync failed: {error}. Inspect ingestion_runs before retrying.\n")


if __name__ == "__main__":
    main()
