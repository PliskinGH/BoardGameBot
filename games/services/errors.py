"""Errors the game services raise, for a front end to translate."""


class ServiceError(Exception):
    """Base class for a refusal a front end can explain to the user."""


class UnknownGame(ServiceError):
    """No definition is registered under the slug."""


class StaleMatch(ServiceError):
    """The client acted on an older version of the match."""


class MatchClosed(ServiceError):
    """The match is not accepting this change."""


class NotASeat(ServiceError):
    """The actor holds no seat in this match."""


class MatchFull(ServiceError):
    """Every seat is taken."""


class AlreadySeated(ServiceError):
    """The actor already holds a seat."""


class SeatsOpen(ServiceError):
    """Some seats are still empty."""


class NothingToUndo(ServiceError):
    """The match has no action to undo."""


class NotYourAction(ServiceError):
    """The live action belongs to another player."""


class UnknownStep(ServiceError):
    """The requested rewind target is not on the log's chain."""


class RewindTooLong(ServiceError):
    """The requested rewind walks back too many actions."""


class UndoForbidden(ServiceError):
    """The action revealed information or used randomness."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason

class NotHost(ServiceError):
    """The actor neither hosts this match nor manages its server."""


class StaleRules(ServiceError):
    """The match was created for another version of the game rules."""


class RulesUpgradeUnavailable(ServiceError):
    """The installed rules cannot carry this match over."""
