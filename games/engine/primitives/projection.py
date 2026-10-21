"""What a seat may see of a zone."""

from collections.abc import Sequence

from .zones import Card


def hand_view(cards: Sequence[Card], *,
              owned: bool) -> tuple[tuple[Card, ...], int | None]:
    """Return the visible cards and, when not owned, how many are hidden."""
    if owned:
        return tuple(cards), None
    return (), len(cards)
