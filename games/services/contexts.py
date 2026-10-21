"""Adapt the stored rows to the plain values the engine reads."""

from collections.abc import Iterable

from games import registry
from games.engine.base import Context, GameDefinition, PendingRef, SeatRef
from games.models import Match, Seat

from .errors import UnknownGame


def definition_for(match: Match) -> GameDefinition:
    """Return the definition of a match, or raise ``UnknownGame``."""
    try:
        return registry.get(match.slug)
    except LookupError:
        raise UnknownGame(match.slug) from None


def definition_for_slug(slug: str) -> GameDefinition:
    """Return the definition registered as ``slug``."""
    try:
        return registry.get(slug)
    except LookupError:
        raise UnknownGame(slug) from None


def seat_refs(seats: Iterable[Seat]) -> tuple[SeatRef, ...]:
    """Return the engine's view of the seats, in play order."""
    return tuple(SeatRef(position=seat.position, role=seat.role,
                         player_id=seat.player_id,
                         name=(seat.display_name
                               or (seat.player.display_name
                                   if seat.player is not None else '')))
                 for seat in seats)


def pending_refs(match: Match) -> tuple[PendingRef, ...]:
    """Return the choices still waiting for an answer."""
    choices = (match.pending_choices.filter(resolved_at__isnull=True)
               .select_related('seat').order_by('pk'))
    return tuple(PendingRef(seat=choice.seat.position, kind=choice.kind,
                            label=choice.label,
                            options=tuple(choice.options))
                 for choice in choices)


def context_for(match: Match,
                seats: Iterable[Seat] | None = None) -> Context:
    """Build the ``Context`` a definition reads for this match."""
    rows = (list(seats) if seats is not None
            else list(match.seats.select_related('player').order_by('position')))
    return Context(
        slug=match.slug, seed=match.seed, options=match.options,
        state=match.state, hidden=match.hidden_state,
        private={seat.position: seat.private_state for seat in rows},
        seats=seat_refs(rows), phase=match.phase,
        active=(match.active_seat.position if match.active_seat else None),
        pending=pending_refs(match))
