"""Lookups over pending choices; opening them is a Transition's job."""

from collections.abc import Sequence
from typing import Any

from ..base import PendingRef


def for_seat(pending: Sequence[PendingRef], seat: int) -> PendingRef | None:
    """Return the choice waiting for ``seat``, if any."""
    for choice in pending:
        if choice.seat == seat:
            return choice
    return None


def is_legal(choice: PendingRef, value: Any) -> bool:
    """Return whether ``value`` is one of the offered answers."""
    return value in choice.options
