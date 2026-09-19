"""Failure-path tests for schema ingestion; no live server is required."""
import copy
import importlib.util
from pathlib import Path
import re
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("metacontext_sync", Path(__file__).parents[1] / "ingestion" / "sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

SCHEMA = {"tables": [{"name": "orders", "columns": [{"name": "id", "type": "TEXT"}]}]}


class Catalog:
    """Persistent fake with an optional committed write whose response is lost."""
    def __init__(self):
        self.rows = {name: {} for name in ("tables", "columns", "ingestion_runs")}
        self.writes = []
        self.fail_after_column_create = False

    def query(self, sql):
        return [{"id": "database1", "endpoint": "http://source.example"}]

    def scan(self, collection, fields, where):
        return copy.deepcopy(list(self.rows[collection].values()))

    def create(self, collection, body):
        self.writes.append((collection, copy.deepcopy(body)))
        record = dict(body, id=f"{collection}{len(self.rows[collection]) + 1}")
        self.rows[collection][record["id"]] = record
        if collection == "columns" and self.fail_after_column_create:
            self.fail_after_column_create = False
            raise sync.SyncError("API connection failed")
        return copy.deepcopy(record)

    def patch(self, collection, record_id, body):
        self.writes.append((collection, copy.deepcopy(body)))
        self.rows[collection][record_id].update(body)
        return copy.deepcopy(self.rows[collection][record_id])


def ingest(catalog, payload):
    with patch.object(sync, "Client") as source:
        source.return_value.request.return_value = copy.deepcopy(payload)
        return sync.sync(catalog, "database1", "source-token")


class SchemaFailureTests(unittest.TestCase):
    def test_rejects_entire_invalid_observation_before_entity_writes(self):
        invalid = [
            None,
            {"tables": {}},
            dict(copy.deepcopy(SCHEMA), truncated=True),
            {"tables": SCHEMA["tables"] * 2},
            {"tables": SCHEMA["tables"] + [{"name": "broken"}]},
            {"tables": SCHEMA["tables"] + [{"name": "broken", "columns": [None]}]},
            {"tables": [{"name": "orders", "columns": [{"name": "id", "type": "TEXT"}] * 2}]},
            {"tables": [{"name": "orders", "columns": [{"name": "id", "type": None}]}]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                catalog = Catalog()
                with self.assertRaises(sync.SyncError):
                    ingest(catalog, payload)
                self.assertTrue(catalog.writes)
                self.assertTrue(all(collection == "ingestion_runs" for collection, _ in catalog.writes))
                self.assertEqual(next(iter(catalog.rows["ingestion_runs"].values()))["status"], "failed")

    def test_response_lost_after_committed_create_retries_without_duplicates(self):
        catalog = Catalog()
        old = catalog.create("tables", {"name": "old", "state": "present", "database": "database1", "description": "Keep this note"})
        catalog.fail_after_column_create = True
        with self.assertRaises(sync.SyncError):
            ingest(catalog, SCHEMA)
        self.assertEqual(catalog.rows["tables"][old["id"]]["state"], "present")
        self.assertEqual(len(catalog.rows["columns"]), 1)
        current = next(row for row in catalog.rows["tables"].values() if row["name"] == "orders")
        current["description"] = "Curated during recovery"
        result = ingest(catalog, SCHEMA)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(catalog.rows["columns"]), 1)
        self.assertEqual(len(catalog.rows["tables"]), 2)
        self.assertEqual(current["description"], "Curated during recovery")
        self.assertEqual(catalog.rows["tables"][old["id"]]["state"], "missing")
        self.assertEqual(catalog.rows["tables"][old["id"]]["description"], "Keep this note")
        self.assertEqual([r["status"] for r in catalog.rows["ingestion_runs"].values()], ["failed", "succeeded"])


class PaginationTests(unittest.TestCase):
    def test_truncated_pages_are_retried_without_skipping_records(self):
        client = sync.Client("http://catalog.example")
        rows = [{"id": f"r{i:03d}", "name": f"table{i}"} for i in range(131)]
        attempts = []

        def query(sql):
            cursor = re.search(r"AND id > '([^']*)'", sql).group(1)
            limit = int(re.search(r"LIMIT (\d+)", sql).group(1))
            attempts.append((cursor, limit))
            if limit > 12:
                raise sync.Truncated("Catalog query was truncated")
            return [row for row in rows if row["id"] > cursor][:limit]

        with patch.object(client, "query", side_effect=query):
            actual = client.scan("tables", "id, name", "1 = 1")
        self.assertEqual(actual, rows)
        self.assertEqual(attempts[:4], [("", 100), ("", 50), ("", 25), ("", 12)])

    def test_irreducible_truncation_fails_instead_of_returning_partial_data(self):
        client = sync.Client("http://catalog.example")
        with patch.object(client, "query", side_effect=sync.Truncated("Too large")) as query:
            with self.assertRaises(sync.Truncated):
                client.scan("tables", "id, name", "1 = 1")
        self.assertEqual(query.call_count, 7)

    def test_query_never_returns_truncated_rows(self):
        client = sync.Client("http://catalog.example")
        with patch.object(client, "request", return_value={"columns": ["id"], "rows": [["one"]], "truncated": True}):
            with self.assertRaises(sync.Truncated):
                client.query("SELECT id FROM tables")


if __name__ == "__main__":
    unittest.main()
