"""An answer as the customer sees it in their terminal: what Signature understood the question to ask, then the
rows it found."""

from typing import Any

from signature_plugin.local_data import Result

SHOWN_ROWS = 50
CELL_WIDTH = 40


def rendered(reading: str | None, result: Result) -> str:
    lines = [f'Signature read your question as: {reading}', ''] if reading else []
    if not result.rows:
        return '\n'.join([*lines, 'No rows match.'])
    shown = result.rows[:SHOWN_ROWS]
    cells = [result.columns, *[[_cell(value) for value in row] for row in shown]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(result.columns))]
    table = [' │ '.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) for row in cells]
    table.insert(1, '─┼─'.join('─' * width for width in widths))
    lines.extend(table)
    hidden = len(result.rows) - len(shown)
    if hidden or result.truncated:
        lines.append(f'… and {"more than " if result.truncated else ""}{hidden} more rows.')
    return '\n'.join(lines)


def _cell(value: Any) -> str:
    text = 'none' if value is None else str(value)
    return text if len(text) <= CELL_WIDTH else text[: CELL_WIDTH - 1] + '…'
