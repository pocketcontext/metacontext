/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const access = "@request.auth.id != '' && @request.auth.collectionName = 'agents'";
  app.save(new Collection({
    type: "auth", name: "agents", listRule: null, viewRule: "id = @request.auth.id",
    createRule: null, updateRule: null, deleteRule: null,
    fields: [{name: "name", type: "text", required: true, max: 200}],
    passwordAuth: {enabled: true, identityFields: ["email"]},
  }));
  const text = (name, required = false, max = 1000) => ({name, type: "text", required, max});
  const relation = (name, collection, required = false) => ({
    name, type: "relation", collectionId: app.findCollectionByNameOrId(collection).id,
    maxSelect: 1, required, cascadeDelete: false,
  });
  const choice = (name, values) => ({name, type: "select", values, maxSelect: 1, required: true});
  function create(name, fields, indexes = []) {
    app.save(new Collection({
      type: "base", name, listRule: access, viewRule: access, createRule: access,
      updateRule: access, deleteRule: null,
      fields: fields.concat([
        {name: "created", type: "autodate", onCreate: true, onUpdate: false},
        {name: "updated", type: "autodate", onCreate: true, onUpdate: true},
      ]), indexes,
    }));
  }
  create("databases", [text("name", true), text("endpoint", true, 2000), text("description", false, 20000)]);
  create("ingestion_runs", [
    relation("database", "databases", true), choice("status", ["running", "succeeded", "failed"]),
    {name: "finished_at", type: "date"}, text("error", false, 2000),
  ], ["CREATE UNIQUE INDEX idx_ingestion_runs_running ON ingestion_runs (database) WHERE status = 'running'"]);
  create("tables", [
    relation("database", "databases", true), text("name", true), text("description", false, 20000),
    choice("state", ["present", "missing"]), relation("last_seen_run", "ingestion_runs"),
  ], ["CREATE UNIQUE INDEX idx_tables_identity ON tables (database, name)"]);
  create("columns", [
    relation("table", "tables", true), text("name", true), text("data_type"), text("description", false, 20000),
    choice("state", ["present", "missing"]), relation("last_seen_run", "ingestion_runs"),
  ], ['CREATE UNIQUE INDEX idx_columns_identity ON columns ("table", name)']);
}, (app) => {
  for (const name of ["columns", "tables", "ingestion_runs", "databases", "agents"]) {
    app.delete(app.findCollectionByNameOrId(name));
  }
});
