# server

The Signature MCP server that runs on the member's machine, and the hook that shows them its answers.

- `server.py` — the MCP server Claude Code starts over stdio: `list_domains`, `describe_domain`, `ask_question`.
- `signature_api.py` — Signature's hosted MCP endpoint, reached with the member's API key.
- `answer_handoff.py` — where the server leaves each answer for the hook, so it never passes through the model.
- `show_answer.py` — the PostToolUse hook that shows the member the answer it finds there.

The hook lives here, not in `hooks/`, because it shares the hand-off with the server. Each script declares its
own dependencies inline and runs with `uv run --script`.
