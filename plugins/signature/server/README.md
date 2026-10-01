# server

The Signature MCP server that runs on the member's machine, and the hook that shows them its answers.

- `server.py` — the MCP server Claude Code starts over stdio: `list_domains`, `describe_domain`, `ask_question`, `report_source` and the domain-building tools.
- `signature_api.py` — Signature's REST API, called with the member's API key.
- `catalog_report.py` — pure: a Postgres catalog's rows become the request Signature takes.
- `catalog_readers.py` — reads that catalog with the member's own connection (`ADAPTERS`: adapter to reader).
- `local_sources.py` — the databases the member declared on this machine, and their connection strings.
- `tests/` — tests of the pure parts and the source config.
- `answer_handoff.py` — where the server leaves each answer for the hook, so it never passes through the model.
- `show_answer.py` — the PostToolUse hook that shows the member the answer it finds there.

The hook lives here, not in `hooks/`, because it shares the hand-off with the server. Each script declares its
own dependencies inline and runs with `uv run --script`.
