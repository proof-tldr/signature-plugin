# Signature plugin: vision

Agreed direction from Ethan, 2026-09-30. None of this is built yet. The plugin will be
rebuilt from scratch around it, replacing the current remote-only version.

## The customer flow

1. The customer installs the Signature plugin for Claude Code.
2. Their Claude creates a new domain and hands Signature everything it can find: documents,
   CSV, TSV and XLSX files, and schemas of SQL databases hosted elsewhere.
3. Signature builds and proves the domain model; the customer publishes it.
4. Questions are answered by SQL that Signature produces, run against the customer's own data.

## Architecture

- **A Claude Code plugin** bundles a local MCP server with skills that teach Claude how to
  set up a Signature domain.
- **The local MCP server** runs on the customer's machine. Claude calls its tools.
- **It calls Signature's REST API directly**, with the customer's API key: the same paths as the
  web app. There is no second MCP server on the backend. The existing remote `/mcp` endpoint
  can stay for cloud-only use.

## Intake: the customer's Claude is our intake agent

The customer's Claude already knows their business and can read their files and databases.
Use that.

- **Send meaning, not just files.** Tools accept Claude's explanation of the data, such as
  "one row per line item; `status=7` means refunded", alongside the data itself.
- **Label provenance.** Every claim is marked *user said* or *Claude inferred*, so the model
  builder weighs it and asks the user to confirm inferred claims.
- **Schemas without credentials.** For remote databases, Claude sends DDL, sample rows and
  notes. The customer never gives us database access.
- **Large files** go through presigned upload, not tool arguments, which pass through
  Claude's context.
- **Privacy default:** schema, samples and descriptions, not full datasets.
- **Clarifying questions** from the model builder (the `clarifications` module) are answered by
  Claude where it can; only real judgment calls go to the human.

Tools this implies: `create_domain`, `add_document`, `describe_dataset`,
`list_clarifications`, `answer_clarification`, `get_domain_status`.

Open: Claude could write TypeSpec itself and call `/domains/import-typespec`. That skips the
model-building conversation, which is the product, so keep it as a fallback only.

## Query execution: Signature runs the SQL, never Claude

Claude running the SQL would be another failure point. Instead:

1. Claude calls `ask_question` on the local server.
2. The local server gets proven SQL from the backend.
3. The local server executes it against the customer's data and returns the result. If the
   backend needs the rows to phrase the answer, the local server sends them back.

Claude sees a question in and an answer out, never the query.

- **Signed queries.** The backend signs each query; the local server verifies the signature
  before running it, so it executes exactly what Signature proved.
- **Read-only role, timeout and row limit** on every connection.
- **A setting for what leaves the machine:** rows, aggregates only, or nothing.
- Database credentials stay in a local config file and never leave the machine.
- **Signature's SQL compiler runs the proven program locally**, translating it to SQL. It ships compiled
  (Nuitka), so the customer installs nothing beyond the plugin and their API key.

## Local files: DuckDB

- **DuckDB is embedded in the local server** and queries CSV, TSV, XLSX and Parquet files
  where they are. This replaces the earlier plan of loading data into MySQL.
- The SQL compiler currently translates to SQLite. Adapt it, and the rest of the stack, to
  DuckDB.
- **Bundle DuckDB's `excel` extension.** Otherwise it downloads on first use, which a
  locked-down corporate network can block.

## Not touching the wrong domain

A customer can have many domains.

- **A domain-scoped API key**, so one connection reaches only one domain. This also lets us set
  a domain up for a customer ahead of time and hand them its key: they start already underway.
  A workspace key stays for building a domain from scratch.
- **Writes land in a draft;** publishing stays a human action in the web app.
- Writes carry the revision Claude last read; stale edits are rejected.
- Confirm destructive calls with MCP elicitation and mark them `destructiveHint`.
- Every tool result names the domain it acted on.

## Decided

- **Answers are shown only to the user.** Claude never reads them; a hook prints them.

## Open questions

- Which language for the local server? DuckDB supports Python, which would let it reuse
  Signature's Python runtime, and Node.
