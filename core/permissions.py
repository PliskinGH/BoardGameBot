"""Guild-scoped match management, on top of guardian."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from django.contrib.sessions.backends.base import SessionBase
from django.db.models import QuerySet
from guardian.shortcuts import assign_perm, get_objects_for_user, remove_perm

from . import discord_api
from .models import Guild, Player

MANAGE_MATCHES = 'core.manage_matches'


class GuildPermissions(Protocol):
    """The one Discord permission this module reads."""

    manage_guild: bool


@dataclass(frozen=True)
class GuildAccess:
    """A guild, and whether Discord lets the player manage it."""

    discord_id: int
    manages: bool


def access_from_session(session: SessionBase) -> list[GuildAccess]:
    """Return the logged in account's guilds and their manage flag."""
    return [GuildAccess(discord_id=int(entry['id']),
                        manages=discord_api.manages_guild(entry))
            for entry in discord_api.session_guilds(session)]


def access_from_member(guild_id: int,
                       permissions: GuildPermissions | None) -> list[GuildAccess]:
    """Return the guild of an interaction and its manage flag."""
    manages = bool(permissions and permissions.manage_guild)
    return [GuildAccess(discord_id=guild_id, manages=manages)]


def seed_managers(player: Player, access: Iterable[GuildAccess]) -> int:
    """Grant the match permission in every known guild marked as managed."""
    ids = [entry.discord_id for entry in access if entry.manages]
    if not ids:
        return 0
    guilds = list(Guild.objects.filter(discord_id__in=ids))
    for guild in guilds:
        grant_manager(guild, player)
    return len(guilds)


def managed_guilds(player: Player) -> QuerySet[Guild]:
    """Return the servers the player may manage matches in."""
    if not player.is_active:
        return Guild.objects.none()
    return get_objects_for_user(player, MANAGE_MATCHES, klass=Guild)


def is_guild_manager(guild: Guild, player: Player) -> bool:
    """Return True when the player may manage this server's matches."""
    return player.is_active and player.has_perm(MANAGE_MATCHES, guild)


def grant_manager(guild: Guild, player: Player) -> None:
    """Give the player the server's match permission."""
    assign_perm(MANAGE_MATCHES, player, guild)


def revoke_manager(guild: Guild, player: Player) -> bool:
    """Withdraw the server's match permission; False when absent."""
    result = remove_perm(MANAGE_MATCHES, player, guild)
    return bool(result and result[0])
