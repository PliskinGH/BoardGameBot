"""Keep the stored choices in step with a Transition."""

from collections.abc import Iterable
from typing import Any

from django.utils import timezone

from games.engine.base import PendingSpec
from games.models import Match, PendingChoice, Seat


def reconcile(match: Match, seats: dict[int, Seat],
              specs: Iterable[PendingSpec], *,
              response: dict[str, Any] | None = None) -> None:
    """Open or close the choices a transition asks for."""
    for spec in specs:
        rows = PendingChoice.objects.filter(
            match=match, seat__position=spec.seat, kind=spec.kind,
            resolved_at__isnull=True)
        if spec.close:
            rows.update(resolved_at=timezone.now(), response=response)
            continue
        if rows.exists():
            rows.update(label=spec.label, options=list(spec.options),
                        context=spec.context)
            continue
        PendingChoice.objects.create(
            match=match, seat=seats[spec.seat], kind=spec.kind,
            label=spec.label, options=list(spec.options),
            context=spec.context)


def snapshot(match: Match) -> list[dict[str, Any]]:
    """Return the open choices as plain data a snapshot can store."""
    choices = (match.pending_choices.filter(resolved_at__isnull=True)
               .select_related('seat').order_by('pk'))
    return [{'seat': choice.seat.position, 'kind': choice.kind,
             'label': choice.label, 'options': choice.options,
             'context': choice.context}
            for choice in choices]


def restore(match: Match, seats: dict[int, Seat],
            entries: Iterable[dict[str, Any]]) -> None:
    """Replace the open choices with the ones a snapshot holds."""
    PendingChoice.objects.filter(match=match,
                                 resolved_at__isnull=True).delete()
    for entry in entries:
        PendingChoice.objects.create(
            match=match, seat=seats[int(entry['seat'])], kind=entry['kind'],
            label=entry.get('label', ''), options=entry.get('options', []),
            context=entry.get('context', {}))
