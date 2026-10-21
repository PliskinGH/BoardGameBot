"""Shape the seats of a render model for the templates."""

from typing import Any

from games.engine.base import RenderModel
from games.models import Match


def rows(model: RenderModel) -> list[dict[str, Any]]:
    """Return one row per seat, with its counters and hidden card count."""
    return [{'position': seat.position,
             'label': seat.label,
             'is_active': seat.is_active,
             'eliminated': seat.eliminated,
             'counters': seat.counters,
             'hidden_cards': seat.hidden_cards}
            for seat in model.seats]


def setup_rows(match: Match) -> list[dict[str, Any]]:
    """Return the seats of a match still waiting to start, in order."""
    return [{'number': seat.position + 1,
             'player': (seat.display_name
                        or (seat.player.display_name if seat.player else ''))}
            for seat in match.seats.all()]
