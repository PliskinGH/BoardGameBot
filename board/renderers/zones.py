"""Shape the zones of a render model for the templates."""

from typing import Any

from bgb_engine.base import RenderModel


def rows(model: RenderModel) -> list[dict[str, Any]]:
    """Return one row per zone, with its visible cards and hidden count."""
    return [{'kind': zone.kind,
             'label': zone.label,
             'cards': [{'id': card.id, 'label': card.label, 'value': card.value}
                       for card in zone.cards],
             'hidden_count': zone.hidden_count}
            for zone in model.zones]
