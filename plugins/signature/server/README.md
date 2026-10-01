# server

The Signature MCP server that runs on the member's machine, and the hook that shows them its answers.

- `server.py` — the MCP server Claude Code starts over stdio: `list_domains`, `describe_domain`, `ask_question`, `report_source`, `report_files`, `answer_clarification` and the other domain-building tools.
- `signature_api.py` — Signature's REST API, called with the member's API key.
- `catalog_report.py` — pure: a Postgres catalog's rows, or the columns DuckDB found in files, become the request Signature takes.
- `catalog_readers.py` — reads a source's structure: Postgres through the member's libpq connection service, files through DuckDB (`ADAPTERS`: adapter to reader).
- `local_files.py` — which files a path, folder or glob names, and their format; opens nothing.
- `tests/` — tests of the pure parts, the readers (against small fixture files in `tests/files/`), the source refusals and the REST calls (against a mock transport).
- `answer_handoff.py` — where the server leaves each answer for the hook, so it never passes through the model.
- `show_answer.py` — the PostToolUse hook that shows the member the answer it finds there.

The hook lives here, not in `hooks/`, because it shares the hand-off with the server. Each script declares its
own dependencies inline and runs with `uv run --script`.
