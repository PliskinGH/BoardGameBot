"""Undo the action the match is standing on, or rewind several steps."""

from typing import Any

from django.db import transaction

from core.models import Player
from games.models import Action, ActionSnapshot, Match, Seat, UndoPolicy
from . import notifier

from .errors import (NothingToUndo, NotYourAction, RewindTooLong, StaleMatch,
                     UndoForbidden, UnknownStep)
from .outbox import enqueue, supersede
from .permissions import require_host
from .snapshots import capture, restore

MAX_REWIND = 100
AUDIT_REASON_LIMIT = 200


def _lock(match_id: int, expected_version: int | None) -> Match:
    match = Match.objects.select_for_update().get(pk=match_id)
    if expected_version is not None and expected_version != match.version:
        raise StaleMatch(f'The table moved to version {match.version}.')
    return match


def _seats(match: Match) -> tuple[list[Seat], dict[int, Seat]]:
    rows = list(match.seats.select_related('player').order_by('position'))
    return rows, {seat.position: seat for seat in rows}


def _live_action(match: Match) -> Action:
    if match.position == 0:
        raise NothingToUndo('There is nothing to undo.')
    action = (Action.objects.select_related('snapshot')
              .filter(match=match, seq=match.position).first())
    if action is None or not hasattr(action, 'snapshot'):
        raise NothingToUndo('That action cannot be reversed.')
    return action


def _check(match: Match, action: Action, actor: Player,
           force: bool) -> None:
    if not force and action.actor_id != actor.pk:
        raise NotYourAction('That action belongs to another player.')
    if action.type == 'rules_upgrade':
        raise UndoForbidden('upgrade')
    if force or match.undo_policy == UndoPolicy.ALL:
        return
    if action.revealed:
        raise UndoForbidden('revealed')
    if action.random:
        raise UndoForbidden('random')


def _audit(force: bool, reason: str) -> dict[str, Any] | None:
    """Return the audit recorded on a forced undo, or None."""
    if not force:
        return None
    return {'forced': True, 'reason': reason.strip()[:AUDIT_REASON_LIMIT]}


def _step(match: Match, seats: dict[int, Seat], rows: list[Seat],
          action: Action, actor: Player,
          audit: dict[str, Any] | None = None) -> Action:
    """Restore one action's snapshot and append the undo row."""
    before = capture(match, rows)
    restore(match, seats, action.snapshot.data)
    match.version += 1
    match.save()
    record = Action.objects.create(
        match=match, seq=match.version, actor=actor, type='undo',
        payload={'undoes': action.seq}, result=audit or {})
    ActionSnapshot.objects.create(action=record, data=before)
    return record


@transaction.atomic
def undo_last_action(match_id: int, actor: Player,
                     expected_version: int | None = None, *,
                     force: bool = False, reason: str = '') -> Match:
    """Undo the live action, restoring the state it replaced."""
    match = _lock(match_id, expected_version)
    if force:
        require_host(match, actor)
    action = _live_action(match)
    _check(match, action, actor, force)
    rows, seats = _seats(match)
    _step(match, seats, rows, action, actor, _audit(force, reason))
    supersede(match)
    enqueue(match)
    version = match.version
    transaction.on_commit(lambda: notifier.game_changed(match.pk, version))
    return match


@transaction.atomic
def rewind_to(match_id: int, target_position: int, actor: Player,
              expected_version: int | None = None, *, force: bool = False,
              limit: int = MAX_REWIND, reason: str = '') -> Match:
    """Undo back to the state after ``target_position``; 0 is the setup."""
    match = _lock(match_id, expected_version)
    if force:
        require_host(match, actor)
    if target_position >= match.position:
        raise UnknownStep('That step is not behind the current position.')

    plan: list[Action] = []
    position = match.position
    while position > target_position:
        action = (Action.objects.select_related('snapshot')
                  .filter(match=match, seq=position).first())
        if action is None or not hasattr(action, 'snapshot'):
            raise UnknownStep('That step is not in the log.')
        _check(match, action, actor, force)
        plan.append(action)
        position = action.snapshot.data['position']
        if len(plan) > limit:
            raise RewindTooLong(f'Rewinding more than {limit} steps is refused.')
    if position != target_position:
        raise UnknownStep('That step is not in the log.')

    rows, seats = _seats(match)
    for action in plan:
        _step(match, seats, rows, action, actor, _audit(force, reason))
    supersede(match)
    enqueue(match)
    version = match.version
    transaction.on_commit(lambda: notifier.game_changed(match.pk, version))
    return match
