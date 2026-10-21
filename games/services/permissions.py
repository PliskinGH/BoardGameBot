"""Who may start, close, upgrade or force-undo a match."""

from core.models import Player
from core.permissions import is_guild_manager
from games.models import Match

from .errors import NotHost


def is_host(match: Match, player: Player) -> bool:
    """Return True when the player opened the table."""
    return match.host_id is not None and match.host_id == player.pk


def may_manage(match: Match, player: Player) -> bool:
    """Return True for the host of the match or a manager of its server."""
    if not player.is_active:
        return False
    return is_host(match, player) or is_guild_manager(match.guild, player)


def require_host(match: Match, player: Player) -> None:
    """Refuse an actor who neither hosts this match nor manages its server."""
    if not may_manage(match, player):
        raise NotHost('Only the host of this match can do that.')
