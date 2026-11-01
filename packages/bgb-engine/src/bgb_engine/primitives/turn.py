"""Seating and turn rotation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnOrder:
    """The seat positions in play order."""

    positions: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.positions:
            raise ValueError('A turn order needs at least one seat.')
        if len(set(self.positions)) != len(self.positions):
            raise ValueError('Seat positions must be unique.')

    def after(self, position: int,
              skip: frozenset[int] = frozenset()) -> int:
        """Return the next seat that is not skipped."""
        index = self.positions.index(position)
        for offset in range(1, len(self.positions) + 1):
            candidate = self.positions[(index + offset) % len(self.positions)]
            if candidate not in skip:
                return candidate
        raise ValueError('Every seat is skipped.')
