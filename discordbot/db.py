"""Bridge between the bot's event loop and Django's synchronous ORM."""

from collections.abc import Callable
from typing import Any, TypeVar

from asgiref.sync import sync_to_async
from discord import Guild as DiscordGuild
from discord import Interaction, Member, User
from django.db import close_old_connections

from core import permissions as core_permissions
from core.models import DiscordAccount, Guild, Player
from games.models import Match

T = TypeVar('T')


def _call(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run one synchronous call with a clean database connection."""
    close_old_connections()
    try:
        return function(*args, **kwargs)
    finally:
        close_old_connections()


async def run_db(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous Django function off the event loop."""
    return await sync_to_async(_call, thread_sensitive=True)(function, *args,
                                                             **kwargs)


def guild_row(discord_guild: DiscordGuild) -> Guild:
    """Return the guild row behind a Discord guild, keeping its name current."""
    guild, created = Guild.objects.get_or_create(
        discord_id=discord_guild.id,
        defaults={'name': discord_guild.name})
    if not created and guild.name != discord_guild.name:
        guild.name = discord_guild.name
        guild.save(update_fields=['name'])
    return guild


async def _guild_row(interaction: Interaction) -> Guild:
    """Return the guild row of the interaction, creating it when missing."""
    guild = interaction.guild
    if guild is None:
        raise ValueError('That command works in a server only.')
    return await run_db(guild_row, guild)


async def seed_managers(interaction: Interaction,
                        guild: Guild | None = None) -> None:
    """Grant the caller's manager permission when Discord allows it.

    ``guild`` reuses a row the caller already loaded; otherwise it is fetched.
    """
    permissions = getattr(interaction.user, 'guild_permissions', None)
    if permissions is None or not permissions.manage_guild:
        return
    row = guild if guild is not None else await _guild_row(interaction)
    player = await player_for(interaction.user)
    await run_db(core_permissions.seed_managers, player,
                 core_permissions.access_from_member(row.discord_id,
                                                     permissions))


async def guild_for(interaction: Interaction) -> Guild:
    """Return the guild row, seeding the caller's match permission."""
    row = await _guild_row(interaction)
    await seed_managers(interaction, row)
    return row


async def player_for(user: Member | User) -> Player:
    """Return the player row behind a Discord user, creating it when missing."""
    return await run_db(Player.objects.from_discord,
                        DiscordAccount(id=user.id, name=user.name))


def match_row(pk: int, discord_guild_id: int) -> Match | None:
    """Return a match of this server, or None when it is not one of its own."""
    return (Match.objects.select_related('guild')
            .filter(pk=pk, guild__discord_id=discord_guild_id).first())
