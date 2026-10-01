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

`report_source` sends Signature a database's structure (tables, columns, keys; never rows). The plugin reads it
itself and sends it directly; your Claude only picks which source by name and sees a table count. Declare sources
in `~/.config/signature/sources.json` (or the file named by `SIGNATURE_SOURCES_FILE`):

```json
{"sources": {"shop": {"adapter": "postgresql", "connection_env": "SHOP_DATABASE_URL"}}}
```

The connection string lives in that environment variable where Claude Code runs, never in the file or in a tool call.
