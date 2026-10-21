"""Capture and restore the persisted state an action may change."""

import copy
from collections.abc import Iterable
from typing import Any

from django.utils.dateparse import parse_datetime

from games.models import Match, Seat

from . import pending


def capture(match: Match, seats: Iterable[Seat]) -> dict[str, Any]:
    """Return the state an action is about to replace."""
    return {
        'state': copy.deepcopy(match.state),
        'hidden_state': copy.deepcopy(match.hidden_state),
        'private': {str(seat.position): copy.deepcopy(seat.private_state)
                    for seat in seats},
        'pending': pending.snapshot(match),
        'active_position': (match.active_seat.position
                            if match.active_seat else None),
        'phase': match.phase,
        'status': match.status,
        'finished_at': (match.finished_at.isoformat()
                        if match.finished_at else None),
        'position': match.position,
    }


def restore(match: Match, seats: dict[int, Seat],
            data: dict[str, Any]) -> None:
    """Put the match and its seats back to a captured state."""
    match.state = copy.deepcopy(data['state'])
    match.hidden_state = copy.deepcopy(data['hidden_state'])
    match.phase = data['phase']
    match.status = data['status']
    match.finished_at = (parse_datetime(data['finished_at'])
                         if data['finished_at'] else None)
    match.position = data['position']
    active = data['active_position']
    match.active_seat = seats[int(active)] if active is not None else None
    for position, private in data['private'].items():
        seat = seats[int(position)]
        seat.private_state = copy.deepcopy(private)
        seat.save(update_fields=['private_state'])
    pending.restore(match, seats, data['pending'])
