"""Decide whether an action made information known to someone new."""

from typing import Any

from games.engine.base import Transition


def tokens(value: Any) -> set[str]:
    """Collect the string tokens a player could recognise in a JSON blob."""
    found: set[str] = set()
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            found |= tokens(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= tokens(item)
    return found


def detect(before: dict[str, Any], transition: Transition) -> bool:
    """Return whether hidden information left its hidden home.

    A card drawn into a hand counts, like a card played face up: both make
    information known to someone who did not know it before.
    """
    hidden_before = tokens(before['hidden_state'])
    hidden_after = tokens({**before['hidden_state'], **transition.hidden})
    public_after = tokens(transition.state)
    private_before = {int(position): tokens(values)
                      for position, values in before['private'].items()}
    private_after = {
        int(position): tokens({**values,
                               **transition.private.get(int(position), {})})
        for position, values in before['private'].items()}
    visible_after: set[str] = set(public_after)
    for visible in private_after.values():
        visible_after |= visible

    if (hidden_before - hidden_after) & visible_after:
        return True
    for seat, owned_before in private_before.items():
        released = owned_before - private_after.get(seat, set())
        if released & public_after:
            return True
        for other, owned_after in private_after.items():
            if other != seat and released & owned_after:
                return True
    return False
