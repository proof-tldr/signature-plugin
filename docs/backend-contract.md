# Backend contract

Every Signature-Platform operation the plugin calls, as `plugins/signature/server/src/signature_plugin/backend.py`
calls it. All requests go to the key API (Beta: `https://d2378glmrsgsno.cloudfront.net`) and carry
`Authorization: Bearer <domain-scoped API key>`. The plugin never sends a domain
id it chose: it reads the one domain the key opens from `GET /domains`.

**Status** says whether Signature-Platform has the operation today (checked against `openapi.json` on
2026-10-01). Until the missing ones exist, run the plugin against the stand-in backend
(`signature-fake-backend`), which implements this whole contract in memory.

| Operation | Status |
| --- | --- |
| `GET /domains` → `{domains: [{id, name}]}`, exactly one for a domain key | exists |
| `GET /domains/{id}` → `{name}` | exists |
| `GET /domains/{id}/publication` → `{publishedAt}`, 404 while unpublished | exists |
| `POST /domains/{id}/documents/presign` `{kind, filename, contentType, size, checksumSha256}` → `{url, contentRef}`, then `PUT url` | exists |
| `PUT /domains/{id}/model/sources/{sourceId}/catalog` `{name, database}` | exists, but needs the one-catalog `duckdb` format below (#240) |
| `POST /domains/{id}/conversation/turns` `{idempotencyKey, text?, sources?}` → `{turn: {id}}` | exists |
| `GET /domains/{id}/conversation/turns/{turnId}` → `{state: pending\|answered\|failed, reply?}` | exists |
| `GET /domains/{id}/conversation/clarifying-questions` → `{questions: [{id, question, suggestedAnswers}]}` | exists |
| `POST /domains/{id}/conversation/clarifying-questions/{questionId}/answer` `{answer}` → `{turn: {id}}` | exists |
| `POST /domains/{id}/publish` | exists; a domain key may call it (checked 2026-10-01) |
| `GET /domains/{id}/model/snapshot` → the whole model, rendered as the review page; its `mappings`, `mappingFields` and `columns` also let the plugin pull real examples from the customer's data | exists |
| `POST /domains/{id}/queries`, `GET /domains/{id}/queries/{queryId}` | **new** (#239) |

## Documents

The plugin uploads each document exactly as the customer gave it, with `kind: "notes"`; it does not classify
documents. A document `kind` that Signature can infer itself would remove that placeholder.

## How it fits together

1. **Build.** The plugin reports the customer's whole local DuckDB as **one catalog**, with a fingerprint of its
   structure. The model conversation produces the domain's `signature.json` and `axioms.json`.
2. **Publish.** The backend runs signiture-sql on that catalog's schema and the domain to build the package
   (`apis.json`, `macros.json`, `sql.json`, proven metrics), stored with the published version and the
   catalog's fingerprint.
3. **Ask.** The plugin sends a question with the fingerprint of its sources now. A mismatch means the sources
   changed after publishing, and the backend answers `stale`; otherwise signiture-sql writes proven DuckDB SQL,
   which the plugin runs locally.

Tracked in Signature-Platform #239 (generation and queries) and #240 (the catalog), and signiture-sql #4 (DuckDB
dialect) and #5 (building from a reported catalog). For the demo, the few text values signiture-sql needs to
match (statuses, region names) are written into the domain's notes by hand; the catalog carries no values.

## Source catalog: one `duckdb` catalog (new, Signature-Platform #240)

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

## Queries (new, Signature-Platform #239)

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
