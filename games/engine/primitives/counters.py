"""Named integer resources, one value per seat position."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Counters:
    """Named counters, each holding one value per seat."""

    values: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, row in self.values.items():
            if any(value < 0 for value in row):
                raise ValueError(f'Counter {name!r} cannot be negative.')

    def get(self, name: str, position: int) -> int:
        try:
            return self.values[name][position]
        except KeyError:
            raise KeyError(f'Unknown counter {name!r}.') from None

    def with_add(self, name: str, position: int, amount: int) -> 'Counters':
        if amount < 0:
            raise ValueError('Use with_take to remove counters.')
        return self._replace(name, position, self.get(name, position) + amount)

    def with_take(self, name: str, position: int, amount: int) -> 'Counters':
        if amount < 0:
            raise ValueError('Use with_add to add counters.')
        return self._replace(name, position,
                             max(0, self.get(name, position) - amount))

    def with_swap(self, name: str, left: int, right: int) -> 'Counters':
        row = list(self.values[name])
        row[left], row[right] = row[right], row[left]
        return Counters({**self.values, name: tuple(row)})

    def as_dict(self) -> dict[str, list[int]]:
        return {name: list(row) for name, row in self.values.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Counters':
        return cls({name: tuple(row) for name, row in data.items()})

    def _replace(self, name: str, position: int, value: int) -> 'Counters':
        row = list(self.values[name])
        row[position] = value
        return Counters({**self.values, name: tuple(row)})
