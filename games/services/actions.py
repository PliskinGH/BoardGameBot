"""The single write path: validate, snapshot, apply and persist."""

from dataclasses import asdict
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Player
from bgb_engine.base import Action as EngineAction
from games.models import (Action, ActionSnapshot, Match, MatchStatus, Seat)
from . import notifier

from .contexts import context_for, definition_for
from .errors import MatchClosed, NotASeat, StaleMatch, StaleRules
from .outbox import enqueue
from .pending import reconcile
from .reveals import detect
from .snapshots import capture


@transaction.atomic
def apply_action(match_id: int, actor: Player, action_id: str,
                 params: dict[str, Any] | None = None,
                 expected_version: int | None = None) -> Match:
    """Apply one action and persist everything it produced.

    The engine's ``IllegalAction`` and the service errors both leave the match
    untouched; only a fully validated transition is written.
    """
    match = Match.objects.select_for_update().get(pk=match_id)
    if match.status != MatchStatus.ACTIVE:
        raise MatchClosed('This match is not being played.')
    if expected_version is not None and expected_version != match.version:
        raise StaleMatch(f'The table moved to version {match.version}.')

    definition = definition_for(match)
    if match.rules_version != definition.version:
        raise StaleRules(f'This match runs {match.slug} rules '
                         f'v{match.rules_version}; the installed rules are '
                         f'v{definition.version}.')
    seats = list(match.seats.select_related('player').order_by('position'))
    by_position: dict[int, Seat] = {seat.position: seat for seat in seats}
    seat = next((row for row in seats if row.player_id == actor.pk), None)
    if seat is None:
        raise NotASeat('You hold no seat in this match.')

    payload = dict(params or {})
    before = capture(match, seats)
    transition = definition.apply(
        context_for(match, seats),
        EngineAction(actor=seat.position, id=action_id, params=payload))

    match.state = transition.state
    if transition.hidden:
        match.hidden_state = {**match.hidden_state, **transition.hidden}
    for position, patch in transition.private.items():
        row = by_position[position]
        row.private_state = {**row.private_state, **patch}
        row.save(update_fields=['private_state'])
    if transition.phase is not None:
        match.phase = transition.phase
    if transition.over:
        match.status = MatchStatus.FINISHED
        match.finished_at = timezone.now()
        match.active_seat = None
    elif transition.active is not None:
        match.active_seat = by_position.get(transition.active)

    match.version += 1
    match.position = match.version
    match.save()

    revealed = (transition.reveals if transition.reveals is not None
                else detect(before, transition))
    record = Action.objects.create(
        match=match, seq=match.version, actor=actor, type=action_id,
        payload=payload,
        result={'log': [asdict(entry) for entry in transition.log]},
        random=transition.random, revealed=revealed)
    ActionSnapshot.objects.create(action=record, data=before)

    reconcile(match, by_position, transition.pending,
              response={'action': action_id, 'params': payload})
    enqueue(match, transition.outbox)

    version = match.version
    transaction.on_commit(lambda: notifier.game_changed(match.pk, version))
    return match
