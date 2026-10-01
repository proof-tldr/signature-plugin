# Signature for Claude Code

Connects Claude Code to Signature. Answers to your questions print in your terminal and are
withheld from the model.

```sh
claude plugin marketplace add proof-tldr/signature-plugin
claude plugin install signature@signature
```

Claude Code asks for your API key during install (create one under Settings → API keys in
Signature) and keeps it in your system keychain.

## What's here

- `plugins/signature/server/server.py` — the Signature MCP server, run on your machine. It reaches
  Signature with your key and offers `list_domains`, `describe_domain` and `ask_question`.
- `plugins/signature/server/show_answer.py` — after `ask_question`, shows you the answer the server
  left for it; the model only learns that it was shown.
- `plugins/signature/hooks/hooks.json` — runs that hook after every `ask_question`.

Requires [uv](https://docs.astral.sh/uv/), which fetches Python and the server's dependencies on
first run.

## Reporting a local database

`report_source` sends Signature a Postgres database's structure (tables, columns, keys; never rows). The plugin
reads it itself and sends it directly; your Claude only picks which source by service name and sees a table
count. Define the service in `~/.pg_service.conf` (or the file named by `PGSERVICEFILE`):

```ini
[shop]
host=db.internal
dbname=shop
user=reader
```

and put its password in `~/.pgpass` (`db.internal:5432:shop:reader:<password>`, mode 0600), as libpq normally reads
it. Then ask Claude to report the `shop` source. No credential is ever a tool argument or output.

## Reporting local files

`report_files` does the same for CSV, TSV, Parquet, JSON and Excel (.xlsx) files: Claude passes a file, a folder or a
glob (`~/data/*.csv`), which is only where to look. [DuckDB](https://duckdb.org/docs/stable/guides/meta/describe) describes
each file's columns on your machine; the plugin sends each file's name, format and column names, types and nullability,
never a row, and Claude sees a table count. Types are inferred from a sample of each file and sent as inferred; you
confirm them in the local review page. Excel reading downloads DuckDB's `excel` extension on first use.
