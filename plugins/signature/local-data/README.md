# signature-local-data

Opens a customer's files (CSV, TSV, XLSX, Parquet, JSON) and databases (PostgreSQL, MySQL) together in one
locked, read-only embedded DuckDB, reports their structure, and runs Signature's SQL. No keychain: the caller
supplies each database's password, and where DuckDB keeps its extensions, spill files and home.

```python
from signature_local_data import DuckDbFolders, FileSource, LocalData

local = LocalData(password_of=lookup, folders=DuckDbFolders(extensions=..., temp=..., home=...))
catalog = local.catalog(sources)
result = local.run(sources, 'SELECT count(*) FROM "memory"."files"."orders"')
```

| Module | Holds |
| --- | --- |
| `sources.py` | `FileSource`, `DatabaseSource`, `Source`, `SourceRefused` |
| `local_data.py` | `LocalData`, `Catalog`, `Result`, `QueryRefused`, `DuckDbFolders` |

```sh
uv sync && uv run pytest && uv run ruff check . && uv run pyright
```
