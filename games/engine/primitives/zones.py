"""Cards and ordered piles; no rule about what a card means."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .rng import rng_for


@dataclass(frozen=True)
class Card:
    """A card the engine moves between zones."""

    id: str
    label: str = ''
    value: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {'id': self.id, 'label': self.label, 'value': self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Card':
        return cls(id=data['id'], label=data.get('label', ''),
                   value=data.get('value', 0))


def shuffled(cards: Sequence[Card], *, seed: int, salt: str = '') -> list[Card]:
    """Return a shuffled copy, reproducible from ``seed`` and ``salt``."""
    pile = list(cards)
    rng_for(seed, salt).shuffle(pile)
    return pile


def find(cards: Sequence[Card], card_id: str) -> Card | None:
    """Return the card with ``card_id``, or ``None``."""
    for card in cards:
        if card.id == card_id:
            return card
    return None


def take(cards: Sequence[Card],
         count: int = 1) -> tuple[list[Card], list[Card]]:
    """Return the first ``count`` cards and the rest of the pile."""
    if count < 0:
        raise ValueError('Cannot take a negative number of cards.')
    return list(cards[:count]), list(cards[count:])


def extract(cards: Sequence[Card], card_id: str) -> tuple[Card, list[Card]]:
    """Return the card with ``card_id`` and the pile without it."""
    card = find(cards, card_id)
    if card is None:
        raise KeyError(card_id)
    return card, [candidate for candidate in cards if candidate.id != card_id]
