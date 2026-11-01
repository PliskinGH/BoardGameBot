"""Create tables, seat players, and start or close a match."""

import secrets
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Guild, Player
from bgb_engine.base import OutboxItem
from games.models import (Action, ActionSnapshot, Match, MatchStatus, Seat,
                          UndoPolicy)
from . import notifier
from ..constants import MATCH_NAME_MAX_LENGTH, MATCH_SEED_BITS

from .contexts import (context_for, definition_for, definition_for_slug,
                       seat_refs)
from .errors import (AlreadySeated, MatchClosed, MatchFull, NotASeat,
                     SeatsOpen)
from .outbox import enqueue
from .permissions import require_host
from .snapshots import capture


@transaction.atomic
def create_match(*, guild: Guild, channel_id: int, slug: str, player: Player,
                 name: str = '', seat_name: str = '',
                 options: dict[str, Any] | None = None,
                 seats: int | None = None,
                 undo_policy: str = UndoPolicy.SAFE,
                 seed: int | None = None) -> Match:
    """Create a table, deal it, and seat its host at position 0."""
    definition = definition_for_slug(slug)
    if undo_policy not in UndoPolicy.values:
        raise ValueError(f'Unknown undo policy {undo_policy!r}.')
    name = name.strip()
    if len(name) > MATCH_NAME_MAX_LENGTH:
        raise ValueError(
            f'The match name must be {MATCH_NAME_MAX_LENGTH} '
            'characters or fewer.')

    count = definition.min_players if seats is None else seats
    if not definition.min_players <= count <= definition.max_players:
        raise ValueError(f'{definition.name} seats {definition.min_players} '
                         f'to {definition.max_players} players.')
    match = Match.objects.create(
        guild=guild, host=player, channel_id=channel_id, slug=slug, name=name,
        options=dict(options or {}),
        seed=(secrets.randbits(MATCH_SEED_BITS)
              if seed is None else seed),
        undo_policy=undo_policy, status=MatchStatus.SETUP,
        rules_version=definition.version,
        phase=definition.initial_phase())
    Seat.objects.bulk_create([
        Seat(match=match, position=index,
             player=player if index == 0 else None,
             display_name=seat_name.strip() if index == 0 else '')
        for index in range(count)])
    rows = list(match.seats.select_related('player').order_by('position'))
    setup = definition.setup(match.options, seat_refs(rows), match.seed)
    match.state = setup.state
    match.hidden_state = setup.hidden
    for row in rows:
        row.private_state = setup.private[row.position]
        row.save(update_fields=['private_state'])
    match.save()
    enqueue(match)
    return match

@transaction.atomic
def remember_seat_name(match_id: int, player: Player,
                       seat_name: str) -> Seat | None:
    """Keep the server display name of a seated player current."""
    name = seat_name.strip()
    if not name:
        return None
    match = Match.objects.select_for_update().get(pk=match_id)
    seat = match.seats.filter(player=player).first()
    if seat is None or seat.display_name == name:
        return seat
    seat.display_name = name
    seat.save(update_fields=['display_name'])
    return seat


def match_title(match: Match, game_name: str) -> str:
    """Return the game and the host's name for the table."""
    if match.name:
        return f'{game_name}: {match.name} (#{match.pk})'
    return f'{game_name} #{match.pk}'




@transaction.atomic
def join_match(match_id: int, player: Player, *,
               seat_name: str = '') -> Seat:
    """Give ``player`` the first free seat."""
    match = Match.objects.select_for_update().get(pk=match_id)
    if match.status != MatchStatus.SETUP:
        raise MatchClosed('This match has already started.')
    if match.seats.filter(player=player).exists():
        raise AlreadySeated('You already hold a seat.')
    seat = match.seats.filter(player__isnull=True).order_by('position').first()
    if seat is None:
        raise MatchFull('Every seat is taken.')
    seat.player = player
    seat.display_name = seat_name.strip()
    seat.save(update_fields=['player', 'display_name'])
    enqueue(match)
    return seat


@transaction.atomic
def leave_match(match_id: int, player: Player) -> Seat:
    """Free the seat ``player`` holds, before the match starts."""
    match = Match.objects.select_for_update().get(pk=match_id)
    if match.status != MatchStatus.SETUP:
        raise MatchClosed('This match has already started.')
    seat = match.seats.filter(player=player).first()
    if seat is None:
        raise NotASeat('You hold no seat in this match.')
    seat.player = None
    seat.display_name = ''
    seat.save(update_fields=['player', 'display_name'])
    enqueue(match)
    return seat


@transaction.atomic
def start_match(match_id: int, actor: Player, *,
                seat_name: str = '') -> Match:
    """Open the match once every seat is taken."""
    match = Match.objects.select_for_update().get(pk=match_id)
    require_host(match, actor)
    if match.status != MatchStatus.SETUP:
        raise MatchClosed('This match has already started.')
    rows = list(match.seats.order_by('position'))
    if not rows or any(seat.player_id is None for seat in rows):
        raise SeatsOpen('Every seat must be taken before the match starts.')
    if seat_name:
        host_seat = next((seat for seat in rows
                          if seat.player_id == actor.pk), None)
        if host_seat is not None:
            host_seat.display_name = seat_name.strip()
            host_seat.save(update_fields=['display_name'])
    match.status = MatchStatus.ACTIVE
    match.active_seat = rows[0]
    match.save(update_fields=['status', 'active_seat'])
    enqueue(match)
    return match


@transaction.atomic
def close_match(match_id: int, actor: Player) -> Match:
    """Close a match early, as a logged and undoable action."""
    match = Match.objects.select_for_update().get(pk=match_id)
    require_host(match, actor)
    if match.status == MatchStatus.FINISHED:
        return match
    seats = list(match.seats.select_related('player').order_by('position'))
    before = capture(match, seats)
    match.status = MatchStatus.FINISHED
    match.finished_at = timezone.now()
    match.active_seat = None
    match.version += 1
    match.position = match.version
    match.save()
    record = Action.objects.create(
        match=match, seq=match.version, actor=actor, type='close_match',
        payload={}, result={})
    ActionSnapshot.objects.create(action=record, data=before)
    scores = definition_for(match).scores(context_for(match, seats))
    enqueue(match, [OutboxItem(kind='match_over',
                              payload={'scores': scores})])
    version = match.version
    transaction.on_commit(lambda: notifier.game_changed(match.pk, version))
    return match
