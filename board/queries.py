"""Read the rows a match page renders, without touching the write path."""

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from core.models import Player
from games.models import Match, MatchStatus
from games.services.contexts import definition_for
from games.services.log import WEB_LIMIT
from games.services.matches import match_title
from games.services.projections import render_model, summary

from .renderers import graph, grid, log, seats, standings, zones


def current_player(request: HttpRequest) -> Player | None:
    """Return the player behind the request, or None for a visitor."""
    user = request.user
    return user if isinstance(user, Player) else None


def match_for_display(discord_guild_id: int, pk: int) -> Match:
    """Return the match, refusing another server's match or an unknown one."""
    return get_object_or_404(
        Match.objects.select_related('guild', 'active_seat__player')
                     .prefetch_related('seats__player'),
        pk=pk, guild__discord_id=discord_guild_id)


def game_name(match: Match) -> str:
    """Return the display name of the match's game."""
    return definition_for(match).name


def state_context(match: Match, player: Player | None,
                  state_url: str) -> dict[str, Any]:
    """Return what the page and its polling fragment both render."""
    model = render_model(match, player)
    name = game_name(match)
    finished = match.status == MatchStatus.FINISHED
    return {
        'match': match,
        'game_name': name,
        'match_title': match_title(match, name),
        'model': model,
        'version': match.version,
        'state_url': state_url,
        'is_setup': match.status == MatchStatus.SETUP,
        'is_finished': finished,
        'setup_seats': seats.setup_rows(match),
        'seats': seats.rows(model),
        'graph': graph.rows(model),
        'grid': grid.rows(model),
        'zones': zones.rows(model),
        'standings': (standings.rows(summary(match, player))
                      if finished else []),
        'log': log.entries(match, limit=WEB_LIMIT),
    }
