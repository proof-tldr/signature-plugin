# Signature for Claude Code

Builds a Signature domain from your data and documents, and answers your questions about it with SQL that
Signature writes and your own machine runs. Answers print in your terminal; Claude never sees them.

```sh
claude plugin marketplace add proof-tldr/signature-plugin
claude plugin install signature@signature
```

Claude Code asks for the API key Signature gave you, which opens one domain, and keeps it in your system
keychain. Then ask Claude to set up Signature. There is nothing else to install: the plugin fetches what it
needs on first start.

## What happens

1. Claude asks where your data lives. Files (CSV, TSV, XLSX, Parquet, JSON) are added by path. For a
   PostgreSQL or MySQL database, a page opens in your browser where you enter the connection yourself; the
   password goes to your keychain and never to Claude or Signature.
2. You give Claude your documents, and it hands them to Signature as they are, with the structure of your
   data and a few example values per column. Your rows stay on your machine.
3. Signature builds the domain and may ask questions, for example when documents disagree. Claude answers
   what it can and asks you the rest.
4. A review page opens in your browser. You publish the domain there, or say what's wrong.
5. You ask questions. Signature writes the SQL; it runs here, read-only, and the answer is shown to you.

See [docs/setup-ux.md](docs/setup-ux.md) for the experience and [docs/vision.md](docs/vision.md) for why.

## Layout

| Path | Holds |
| --- | --- |
| `plugins/signature/.mcp.json` | Starts the server through `bin/signature` with your key |
| `plugins/signature/bin/signature` | The launcher: runs the server on its own pinned Python, fetching `uv` if the machine has none |
| `plugins/signature/hooks/hooks.json` | Shows each answer to you after `ask_question` |
| `plugins/signature/skills/setup/SKILL.md` | `/signature:setup`, the setup flow Claude follows |
| `plugins/signature/server/` | The MCP server, a Python package (below) |
| `docs/backend-contract.md` | Every Signature API operation the plugin uses, and which are not built yet |

In `plugins/signature/server/src/signature_plugin/`:

| Module | Does |
| --- | --- |
| `server.py` | The MCP tools, each one step of the flow |
| `backend.py` | Signature's REST API, bound to the key's one domain |
| `sources.py` | Which files and databases the customer added; passwords in the keychain |
| `local_data.py` | Opens every source in one locked, read-only DuckDB; reports structure; runs Signature's SQL |
| `pages.py`, `templates/`, `review.py` | The local browser pages for connecting a database and reviewing the domain, the review drawn from Signature's model snapshot |
| `handoff.py`, `show_answer.py`, `presentation.py` | Getting an answer to the customer without it reaching Claude |
| `fake_backend.py` | A stand-in Signature implementing the contract, for development and rehearsal |

## Development

From `plugins/signature/server`:

```sh
uv sync
uv run pytest                    # the suite; database tests need SIGNATURE_TEST_POSTGRES / SIGNATURE_TEST_MYSQL
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

`SIGNATURE_TEST_POSTGRES=host:port:database:user:password` (and `SIGNATURE_TEST_MYSQL`) runs the tests that
connect a real database through the browser page.

To try the whole thing in Claude Code before Signature-Platform has every endpoint, run the stand-in and point
the plugin at it:

```sh
uv run signature-fake-backend --port 8790
SIGNATURE_API_URL=http://127.0.0.1:8790 claude --plugin-dir plugins/signature
```

Without `SIGNATURE_API_URL`, the plugin uses Beta's key API (`KeyApiUrl`, https://d2378glmrsgsno.cloudfront.net).
The stand-in accepts any key.
