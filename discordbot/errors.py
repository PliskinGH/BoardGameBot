"""Words a player is given when a service refuses an operation."""

from django.utils.translation import gettext_lazy as _

from games.engine.base import IllegalAction
from games.services.errors import (AlreadySeated, MatchClosed, MatchFull,
                                   NotASeat, NotHost, NothingToUndo,
                                   NotYourAction,
                                   RulesUpgradeUnavailable, SeatsOpen,
                                   StaleMatch, StaleRules, UndoForbidden,
                                   UnknownGame)


class NoMatch(Exception):
    """No match of this server is open, or the one named is gone."""


def refusal_text(error: Exception) -> str:
    """Return the sentence a player is shown for a refused operation."""
    if isinstance(error, NoMatch):
        return str(error)
    if isinstance(error, UnknownGame):
        return str(_('That game is not installed.'))
    if isinstance(error, MatchClosed):
        return str(_('This match is not open for that.'))
    if isinstance(error, MatchFull):
        return str(_('Every seat is taken.'))
    if isinstance(error, AlreadySeated):
        return str(_('You already hold a seat.'))
    if isinstance(error, SeatsOpen):
        return str(_('Every seat must be taken before the match starts.'))
    if isinstance(error, NotASeat):
        return str(_('You hold no seat in this match.'))
    if isinstance(error, NotHost):
        return str(_('Only the host of this match, or a manager of this '
                     'server, can do that.'))
    if isinstance(error, NothingToUndo):
        return str(_('There is nothing to undo.'))
    if isinstance(error, NotYourAction):
        return str(_('That was not your action.'))
    if isinstance(error, StaleMatch):
        return str(_('The table moved on; try again.'))
    if isinstance(error, StaleRules):
        return str(_('This match runs older rules than the bot.'))
    if isinstance(error, UndoForbidden):
        return {
            'revealed': str(_('That action revealed information, so only a '
                              'host or a manager can undo it.')),
            'random': str(_('That action used randomness, so only a host or '
                            'a manager can undo it.')),
            'upgrade': str(_('A rules upgrade cannot be undone.')),
        }.get(error.reason, str(_('That action cannot be undone.')))
    if isinstance(error, RulesUpgradeUnavailable):
        return str(_('This match cannot be moved to the installed rules.'))
    if isinstance(error, IllegalAction):
        return str(_('That move is not legal here.'))
    return str(error)
