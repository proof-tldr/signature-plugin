# Backend contract

Every operation of Signature's REST API the plugin calls, as `plugins/signature/server/src/signature_plugin/backend.py`
calls it. All requests go to Signature's API (`https://d2378glmrsgsno.cloudfront.net`) and carry
`Authorization: Bearer <domain-scoped API key>`. The plugin never sends a domain
id it chose: it reads the one domain the key opens from `GET /domains`.

**Status** says whether Signature's API has the operation today (checked against its OpenAPI description on
2026-10-01). Until the missing ones exist, run the plugin against the stand-in backend
(`signature-fake-backend`), which implements this whole contract in memory.

| Operation | Status |
| --- | --- |
| `GET /domains` → `{domains: [{id, name}]}`, exactly one for a domain key | exists |
| `GET /domains/{id}` → `{name}` | exists |
| `GET /domains/{id}/publication` → `{publishedAt}`, 404 while unpublished | exists |
| `POST /domains/{id}/documents/presign` `{kind, filename, contentType, size, checksumSha256}` → `{url, contentRef}`, then `PUT url` | exists |
| `PUT /domains/{id}/model/sources/{sourceId}/catalog` `{name, database}` | the one-catalog `duckdb` format below: in progress |
| `POST /domains/{id}/conversation/turns` `{idempotencyKey, text?, sources?}` → `{turn: {id}}` | exists |
| `GET /domains/{id}/conversation/turns/{turnId}` → `{state: pending\|answered\|failed, reply?, progress: {stages: [{label, startedAt, completedAt?}]}}` | exists |
| `GET /domains/{id}/conversation/clarifying-questions` → `{questions: [{id, question, suggestedAnswers}]}` | exists |
| `POST /domains/{id}/publish` | exists; a domain key may call it (checked 2026-10-01) |
| `GET /domains/{id}/model/snapshot` → the whole model, rendered as the review page; its `mappings`, `mappingFields` and `columns` also let the plugin pull real examples from the customer's data | exists |
| `GET /domains/{id}/query-package` → `{status: queued\|running\|failed\|succeeded, reason, fingerprint, …}`, 404 when the last publication needs none | in progress |
| `POST /domains/{id}/queries`, `GET /domains/{id}/queries/{queryId}` | in progress |

## Documents

The plugin uploads each document exactly as the customer gave it, with `kind: "notes"`; it does not classify
documents. A document `kind` that Signature can infer itself would remove that placeholder.

## How it fits together

1. **Build.** The plugin reports the customer's whole local DuckDB as **one catalog**, with a fingerprint of its
   structure. The model conversation produces the domain's `signature.json` and `axioms.json`.
2. **Publish.** The backend runs its SQL compiler on that catalog's schema and the domain to build the package
   (`apis.json`, `macros.json`, `sql.json`, proven metrics), stored with the published version and the
   catalog's fingerprint.
3. **Ask.** The plugin sends a question with the fingerprint of its sources now. A mismatch means the sources
   changed after publishing, and the backend answers `stale`; otherwise the SQL compiler writes proven DuckDB SQL,
   which the plugin runs locally.

For the demo, the few text values the SQL compiler needs to
match (statuses, region names) are written into the domain's notes by hand; the catalog carries no values.

## Source catalog: one `duckdb` catalog

Reported on every build under one fixed `sourceId` per domain (named "Your data"), replacing the previous one,
with `database: {adapter: "duckdb", catalog}`:

```json
{"fingerprint": "sha256 of the tables below",
 "tables": [
   {"catalog": "memory", "schema": "files", "name": "products",
    "columns": [{"name": "title", "nativeType": "VARCHAR", "nullable": true}],
    "primaryKey": []},
   {"catalog": "sales", "schema": "public", "name": "orders",
    "columns": [{"name": "status", "nativeType": "VARCHAR", "nullable": true}],
    "primaryKey": ["id"]}
 ]}
```

- A table's SQL name is always `"catalog"."schema"."name"`. Data files live in DuckDB's own in-memory catalog,
  `"memory"."files"."<name>"`; an attached database's tables are `"<source>"."<schema>"."<table>"`.
- In the model snapshot, a table's `relation` is that same name unquoted, `catalog.schema.name`. The review page
  reads where each thing comes from off it, and the plugin queries it for real examples.
- `nativeType` is DuckDB's type name, whatever the source's own type was.
- No values from the data.

## Getting ready to answer

Publishing a domain with the plugin's catalog starts building its query package with the SQL compiler in the
background. After publishing, the review tool polls `GET /domains/{id}/query-package` until it is no longer
`queued` or `running`, and tells Claude whether questions can be asked, or why not. A question asked earlier
simply waits behind the build.

## Queries

The customer's data never leaves their machine, so Signature plans a query and the plugin runs it.

`POST /domains/{id}/queries` `{idempotencyKey, question, threadId, fingerprint}` → `202 {id}`

`GET /domains/{id}/queries/{queryId}` →

```json
{"id": "…", "threadId": "…", "state": "pending | planned | unanswerable | stale | failed",
 "reading": "what Signature understood the question to ask, in English",
 "sql": "one DuckDB SELECT over the reported tables",
 "reason": "why it is unanswerable or stale"}
```

The plugin runs `sql` only if it is a single `SELECT` that calls no table function, on a DuckDB that is locked
(`enable_external_access = false`, only the registered files readable, databases attached read-only), within
120 seconds and 10,000 rows. It shows the customer `reading` and the rows; Claude sees neither. On `stale` it
tells the customer their sources changed and rebuilds before asking again.
