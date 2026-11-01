"""Move a match to the rules version the deployed code ships."""

from django.db import transaction

from core.models import Player
from bgb_engine.base import Setup, UpgradableRules
from games.models import Action, ActionSnapshot, Match, MatchStatus
from . import notifier

from .contexts import definition_for, seat_refs
from .errors import RulesUpgradeUnavailable, StaleMatch
from .outbox import enqueue
from .permissions import require_host
from .snapshots import capture


@transaction.atomic
def upgrade_match(match_id: int, actor: Player,
                  expected_version: int | None = None) -> Match:
    """Rebuild or migrate the match state under the installed rules."""
    match = Match.objects.select_for_update().get(pk=match_id)
    require_host(match, actor)
    if expected_version is not None and expected_version != match.version:
        raise StaleMatch(f'The table moved to version {match.version}.')
    definition = definition_for(match)
    if match.rules_version == definition.version:
        return match

    name = definition.name
    seats = list(match.seats.select_related('player').order_by('position'))
    setup: Setup | None
    if match.status == MatchStatus.SETUP:
        setup = definition.setup(match.options, seat_refs(seats), match.seed)
    else:
        if match.pending_choices.filter(resolved_at__isnull=True).exists():
            raise RulesUpgradeUnavailable(
                'Resolve the open choices before upgrading the rules.')
        if not isinstance(definition, UpgradableRules):
            raise RulesUpgradeUnavailable(
                f'{name} cannot upgrade a match in progress.')
        setup = definition.upgrade(
            match.rules_version, match.state, match.hidden_state,
            {seat.position: seat.private_state for seat in seats},
            seat_refs(seats), match.options, match.seed)
        if setup is None:
            raise RulesUpgradeUnavailable(
                f'{name} cannot migrate this state.')

    before = capture(match, seats)
    old_version = match.rules_version
    match.state = setup.state
    match.hidden_state = setup.hidden
    for seat in seats:
        if seat.position in setup.private:
            seat.private_state = setup.private[seat.position]
            seat.save(update_fields=['private_state'])
    match.rules_version = definition.version
    match.version += 1
    match.position = match.version
    match.save()

    record = Action.objects.create(
        match=match, seq=match.version, actor=actor, type='rules_upgrade',
        payload={'from': old_version, 'to': definition.version}, result={})
    ActionSnapshot.objects.create(action=record, data=before)
    enqueue(match)
    version = match.version
    transaction.on_commit(lambda: notifier.game_changed(match.pk, version))
    return match


