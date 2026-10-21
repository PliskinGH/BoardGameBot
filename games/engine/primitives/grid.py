"""A square or hex grid, addressed by column and row."""

from dataclasses import dataclass

SQUARE_OFFSETS = ((0, -1), (-1, 0), (1, 0), (0, 1))
EVEN_ROW_OFFSETS = ((0, -1), (-1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1))
ODD_ROW_OFFSETS = ((0, -1), (1, -1), (-1, 0), (1, 0), (0, 1), (1, 1))


@dataclass(frozen=True)
class BoardGrid:
    """A board of squares (four neighbours) or hexes (six)."""

    columns: int
    rows: int
    hexes: bool = False

    def __post_init__(self) -> None:
        if self.columns < 1 or self.rows < 1:
            raise ValueError('A grid needs at least one column and one row.')

    def in_bounds(self, column: int, row: int) -> bool:
        return 0 <= column < self.columns and 0 <= row < self.rows

    def key(self, column: int, row: int) -> str:
        return f'{column},{row}'

    def neighbours(self, column: int, row: int) -> tuple[tuple[int, int], ...]:
        """Return the in-bounds neighbours of a cell, in odd-r offset."""
        offsets: tuple[tuple[int, int], ...] = SQUARE_OFFSETS
        if self.hexes:
            offsets = ODD_ROW_OFFSETS if row % 2 else EVEN_ROW_OFFSETS
        return tuple((column + dc, row + dr) for dc, dr in offsets
                     if self.in_bounds(column + dc, row + dr))

