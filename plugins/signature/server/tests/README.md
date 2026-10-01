# tests

Tests of the pure parts and the local source config. Run from this folder's parent:

    uv run --with pytest --with 'psycopg[binary]' --with 'duckdb>=1.4' --with mcp==2.2.0 --with httpx2 pytest tests
