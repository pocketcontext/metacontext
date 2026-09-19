/// <reference path="../pb_data/types.d.ts" />
// Run after PocketBase validates field values and relation targets.
onRecordValidate((e) => {
  e.next();
  const record = e.record, name = record.collection().name;
  const identity = name === "tables" ? ["database", "name"] : name === "columns" ? ["table", "name"] : ["database"];
  const fail = (field, message) => {
    throw new BadRequestError(message, {[field]: new ValidationError("validation_catalog_integrity", message)});
  };
  if (!record.isNew()) {
    for (const field of identity) {
      if (record.getString(field) !== record.original().getString(field)) {
        fail(field, field + " is immutable; register a new identity instead");
      }
    }
  }
  if (name === "ingestion_runs") return;
  const runId = record.getString("last_seen_run");
  if (runId === "") return;
  const database = name === "tables" ? record.getString("database") :
    e.app.findRecordById("tables", record.getString("table")).getString("database");
  if (e.app.findRecordById("ingestion_runs", runId).getString("database") !== database) {
    fail("last_seen_run", "last_seen_run must belong to the entity's database");
  }
}, "tables", "columns", "ingestion_runs");
