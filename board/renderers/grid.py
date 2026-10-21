"""Shape a grid render model for the templates."""

from typing import Any

from games.engine.base import GridView, RenderModel


def rows(model: RenderModel) -> dict[str, Any] | None:
    """Return the board cells grouped into rows, or None without a grid."""
    board = model.board
    if not isinstance(board, GridView):
        return None
    cells = {(cell.column, cell.row): cell for cell in board.cells}
    rows = []
    for row in range(board.rows):
        line = []
        for column in range(board.columns):
            cell = cells.get((column, row))
            line.append({
                'column': column,
                'row': row,
                'column_number': column + 1,
                'row_number': row + 1,
                'label': cell.label if cell else '',
                'kind': cell.kind if cell else 'hidden',
                'tokens': [{'node': token.node,
                            'label': token.label,
                            'owner': token.owner}
                           for token in cell.tokens] if cell else [],
            })
        rows.append(line)
    return {'columns': board.columns, 'rows': board.rows,
            'hexes': board.hexes,
            'column_numbers': list(range(1, board.columns + 1)),
            'cells': rows}
