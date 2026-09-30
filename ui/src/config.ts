export interface Entity {
  table: string;
  label: string;
  title: string[];
  subtitle?: string[];
  search: string[];
  filters?: Record<string, string[]>;
  relations?: Record<string, string>;
  hidden?: string[];
  markdown?: string[];
  menu?: boolean;
  relationLabels?: Record<string, string>;
  reverseLabels?: Record<string, string>;
}
export const app: {
  name: string;
  authCollection: string;
  google?: boolean;
  entities: Entity[];
} = {
  name: "MetaContext",
  google: false,
  authCollection: "agents",
  entities: [
    {
      table: "databases",
      label: "Databases",
      title: ["name"],
      search: ["name", "description"],
      markdown: ["description"],
    },
    {
      table: "tables",
      label: "Tables",
      title: ["name"],
      search: ["name", "description"],
      subtitle: ["state"],
      filters: {
        state: ["present", "missing"],
      },
      relations: {
        database: "databases",
        last_seen_run: "ingestion_runs",
      },
      markdown: ["description"],
    },
    {
      table: "columns",
      label: "Columns",
      title: ["name"],
      search: ["name", "description", "data_type"],
      subtitle: ["data_type", "state"],
      filters: {
        state: ["present", "missing"],
      },
      relations: {
        table: "tables",
        last_seen_run: "ingestion_runs",
      },
      markdown: ["description"],
    },
    {
      table: "ingestion_runs",
      label: "Ingestion runs",
      title: ["status", "created"],
      search: ["status", "error"],
      filters: {
        status: ["running", "succeeded", "failed"],
      },
      relations: {
        database: "databases",
      },
      markdown: ["error"],
    },
  ],
};
