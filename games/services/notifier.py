"""Told when a match changed; no transport until push lands."""


def game_changed(match_pk: int, version: int) -> None:
    """Announce a new match version; polling needs nothing yet."""
    return None
