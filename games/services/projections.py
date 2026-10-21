"""Render a match through its definition, for one viewer."""

from typing import Any

from core.models import Player
from games.engine.base import Context, GameDefinition, RenderModel
from games.models import Match

from .contexts import context_for, definition_for


def viewer_position(match: Match, player: Player | None) -> int | None:
    """Return the seat position of ``player``, or ``None`` for a spectator."""
    if player is None:
        return None
    seat = match.seats.filter(player=player).only('position').first()
    return seat.position if seat else None


def _context(match: Match) -> tuple[GameDefinition, Context]:
    seats = list(match.seats.select_related('player').order_by('position'))
    return definition_for(match), context_for(match, seats)


def render_model(match: Match,
                 player: Player | None = None) -> RenderModel:
    """Return the render model this viewer may see."""
    definition, ctx = _context(match)
    return definition.view(ctx, viewer_position(match, player))


def summary(match: Match,
            player: Player | None = None) -> dict[str, Any]:
    """Return the compact summary this viewer may see."""
    definition, ctx = _context(match)
    return definition.summary(ctx, viewer_position(match, player))
