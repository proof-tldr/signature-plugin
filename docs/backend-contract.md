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
| `PUT /domains/{id}/model/sources/{sourceId}/catalog` `{name, database}` | exists, but needs the `duckdb` adapter below |
| `POST /domains/{id}/conversation/turns` `{idempotencyKey, text?, sources?}` → `{turn: {id}}` | exists |
| `GET /domains/{id}/conversation/turns/{turnId}` → `{state: pending\|answered\|failed, reply?}` | exists |
| `GET /domains/{id}/conversation/clarifying-questions` → `{questions: [{id, question, suggestedAnswers}]}` | exists |
| `POST /domains/{id}/conversation/clarifying-questions/{questionId}/answer` `{answer}` → `{turn: {id}}` | exists |
| `POST /domains/{id}/publish` | exists; a domain key may call it (checked 2026-10-01) |
| `GET /domains/{id}/review` | **new** |
| `POST /domains/{id}/queries`, `GET /domains/{id}/queries/{queryId}` | **new** |

## Documents

The plugin uploads each document exactly as the customer gave it, with `kind: "notes"`; it does not classify
documents. A document `kind` that Signature can infer itself would remove that placeholder.

## Source catalogs: the `duckdb` adapter (new)

The customer's files and databases are opened together in one DuckDB on their machine. Each source is reported
with `database: {adapter: "duckdb", catalog}`:

```json
{
  "tables": [
    {
      "schema": "public",
      "name": "orders",
      "sqlName": "\"sales\".\"public\".\"orders\"",
      "columns": [
        {"name": "status", "type": "VARCHAR", "nullable": true, "primaryKey": false,
         "examples": ["paid", "refunded"]}
      ]
    }
  ]
}
```

- `sqlName` is how Signature's SQL must name the table. Files are views `"files"."<source>"`; databases are
  attached as catalogs, so their tables are `"<source>"."<schema>"."<table>"`.
- `type` is DuckDB's type name, whatever the source's own type was.
- `primaryKey` is known for PostgreSQL tables and is false elsewhere. Foreign keys are not reported yet.
- `examples` holds up to five distinct values per column, from the first 1,000 rows, each at most 80
  characters. They let Signature see codes and formats. Whole rows never leave the machine.

## Review (new)

`GET /domains/{id}/review` → `{summary, sections: [{title, points: [string]}]}`: the domain in plain English,
for the customer to read before publishing. The plugin renders it as given.

## Queries (new)

The customer's data never leaves their machine, so Signature plans a query and the plugin runs it.

`POST /domains/{id}/queries` `{idempotencyKey, question, threadId}` → `202 {id}`

`GET /domains/{id}/queries/{queryId}` →

```json
{"id": "…", "threadId": "…", "state": "pending | planned | unanswerable | failed",
 "reading": "what Signature understood the question to ask, in English",
 "sql": "one DuckDB SELECT over the reported sqlNames",
 "reason": "why it is unanswerable"}
```

The plugin runs `sql` only if it is a single `SELECT` that calls no table function, on a DuckDB that is locked
(`enable_external_access = false`, only the registered files readable, databases attached read-only), within
120 seconds and 10,000 rows. It shows the customer `reading` and the rows; Claude sees neither.
