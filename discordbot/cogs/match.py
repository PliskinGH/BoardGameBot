"""The /match commands: open a table, seat players, and play it."""

import logging

import discord
from discord import app_commands
from discord.ext import commands
from django.utils.translation import gettext_lazy as _

from core import permissions as core_permissions
from games.models import Match, UndoPolicy
from games.services import matches, outbox, upgrades
from games.services.errors import ServiceError
from games.services.log import BOARD_LIMIT, entries as log_entries
from games.services.projections import render_model

from .. import choices, db, embeds, errors, replies, views

logger = logging.getLogger(__name__)


async def game_autocomplete(
        interaction: discord.Interaction,
        current: str) -> list[app_commands.Choice[str]]:
    """Offer the installed games by name and slug."""
    return choices.game_choices(current)


async def match_autocomplete(
        interaction: discord.Interaction,
        current: str) -> list[app_commands.Choice[str]]:
    """Offer the open matches of this channel."""
    return await choices.match_choices(interaction, current)


class MatchCog(commands.Cog):
    """Open and play a board-game match in a Discord channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    match = app_commands.Group(name='match',
                               description='Open and play a match here.')

    @match.command(name='new',
                   description='Open a new match in this channel.')
    @app_commands.guild_only()
    @app_commands.describe(game='The game to play.',
                           seats='How many seats the table has.',
                           policy='Which actions may be undone.',
                           name='A name for this table.')
    @app_commands.choices(policy=[
        app_commands.Choice(name='Safe: only what revealed nothing',
                            value=UndoPolicy.SAFE),
        app_commands.Choice(name='All actions', value=UndoPolicy.ALL)])
    @app_commands.autocomplete(game=game_autocomplete)
    async def new(self, interaction: discord.Interaction, game: str,
                  seats: int | None = None,
                  policy: str = UndoPolicy.SAFE,
                  name: str = '') -> None:
        """Open a match, seating the caller first."""
        await interaction.response.defer(ephemeral=True)
        try:
            guild = await db.guild_for(interaction)
            player = await db.player_for(interaction.user)
            definition = choices.resolve_game(game)
            match = await db.run_db(
                matches.create_match, guild=guild,
                channel_id=interaction.channel_id or 0,
                slug=definition.slug, player=player, seats=seats,
                undo_policy=policy, name=name or '',
                seat_name=interaction.user.display_name)
        except (ServiceError, ValueError) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction, content=str(
            _('Match #%(pk)s opened. Its board is on its way.')
            % {'pk': match.pk}))

    @match.command(name='join', description='Take a free seat at a match.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to join.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def join(self, interaction: discord.Interaction,
                   match: str | None = None) -> None:
        """Seat the caller at the first free seat."""
        await interaction.response.defer(ephemeral=True)
        try:
            row = await choices.resolve_match(interaction, match)
            player = await db.player_for(interaction.user)
            seat = await db.run_db(matches.join_match, row.pk, player,
                                   seat_name=interaction.user.display_name)
        except (ServiceError, errors.NoMatch) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction, content=str(
            _('Seat %(number)s is yours.') % {'number': seat.position + 1}))

    @match.command(name='leave', description='Free your seat before the start.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to leave.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def leave(self, interaction: discord.Interaction,
                    match: str | None = None) -> None:
        """Free the seat of the caller."""
        await interaction.response.defer(ephemeral=True)
        try:
            row = await choices.resolve_match(interaction, match)
            player = await db.player_for(interaction.user)
            await db.run_db(matches.leave_match, row.pk, player)
        except (ServiceError, errors.NoMatch) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction, content=str(_('Your seat is free.')))

    @match.command(name='start',
                   description='Start the match once every seat is taken.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to start.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def start(self, interaction: discord.Interaction,
                    match: str | None = None) -> None:
        """Open the table for play."""
        await interaction.response.defer(ephemeral=True)
        try:
            row = await choices.resolve_match(interaction, match)
            player = await db.player_for(interaction.user)
            await db.run_db(matches.start_match, row.pk, player,
                            seat_name=interaction.user.display_name)
        except (ServiceError, errors.NoMatch) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction, content=str(_('The match started.')))

    @match.command(name='close',
                   description='Close the match; hosts and managers only.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to close.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def close(self, interaction: discord.Interaction,
                    match: str | None = None) -> None:
        """Close the table as an undoable action."""
        await interaction.response.defer(ephemeral=True)
        try:
            row = await choices.resolve_match(interaction, match)
            player = await db.player_for(interaction.user)
            await db.run_db(matches.close_match, row.pk, player)
        except (ServiceError, errors.NoMatch) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction, content=str(_('The match is closed.')))

    @match.command(name='upgrade',
                   description='Move the match to the installed rules.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to upgrade.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def upgrade(self, interaction: discord.Interaction,
                      match: str | None = None) -> None:
        """Rebuild the table under the deployed rules."""
        await interaction.response.defer(ephemeral=True)
        try:
            row = await choices.resolve_match(interaction, match)
            player = await db.player_for(interaction.user)
            await db.run_db(upgrades.upgrade_match, row.pk, player,
                            row.version)
        except (ServiceError, errors.NoMatch) as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return
        await replies.reply(interaction,
                            content=str(_('The match now runs the '
                                          'installed rules.')))

    @match.command(name='act', description='Show the moves you may make now.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to play in.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def act(self, interaction: discord.Interaction,
                  match: str | None = None) -> None:
        """Open the private move panel of the caller."""
        row = await self._match(interaction, match)
        if row is not None:
            await views.open_panel(interaction, row.pk)

    @match.command(name='undo',
                   description='Undo the action the table stands on.')
    @app_commands.guild_only()
    @app_commands.describe(
        match='The match to undo in.',
        force='Hosts and managers only: undo a reveal or a random action.',
        reason='Why a forced undo is needed.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def undo(self, interaction: discord.Interaction,
                   match: str | None = None, force: bool = False,
                   reason: str = '') -> None:
        """Undo the live action, within the match's undo policy."""
        row = await self._match(interaction, match)
        if row is None:
            return
        if force and not reason.strip():
            await replies.reply(interaction,
                                content=str(_('Give a reason for a forced '
                                              'undo.')))
            return
        await views.undo_match(interaction, row.pk, force=force, reason=reason)

    @match.command(name='private',
                   description='Show the information only you may see.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match whose private information you want.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def private(self, interaction: discord.Interaction,
                      match: str | None = None) -> None:
        """Show the private information of the caller's seat."""
        row = await self._match(interaction, match)
        if row is not None:
            await views.show_private(interaction, row.pk)

    @match.command(name='hand',
                   description='Compatibility alias for /match private.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match whose private information you want.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def hand(self, interaction: discord.Interaction,
                   match: str | None = None) -> None:
        """Compatibility alias for the private information command."""
        row = await self._match(interaction, match)
        if row is not None:
            await views.show_private(interaction, row.pk)

    @match.command(name='board',
                   description='Repost or refresh the board message.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match whose board you want.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def board(self, interaction: discord.Interaction,
                    match: str | None = None) -> None:
        """Queue a board refresh, which reposts a board that was deleted."""
        await interaction.response.defer(ephemeral=True)
        row = await self._match(interaction, match)
        if row is None:
            return
        await db.run_db(outbox.enqueue, row)
        content = str(_('Refreshing the board.'))
        link = views.web_url(row)
        if link:
            content = f'{content}\n{link}'
        await replies.reply(interaction, content=content)

    @match.command(name='status', description='Show the state of a match.')
    @app_commands.guild_only()
    @app_commands.describe(match='The match to show.')
    @app_commands.autocomplete(match=match_autocomplete)
    async def status(self, interaction: discord.Interaction,
                     match: str | None = None) -> None:
        """Show the state of the table, private to the caller."""
        row = await self._match(interaction, match)
        if row is None:
            return
        player = await db.player_for(interaction.user)
        model = await db.run_db(render_model, row, player)
        name = await db.run_db(views.game_name, row)
        pending = await db.run_db(views.pending_choice, row)
        log = await db.run_db(log_entries, row, limit=BOARD_LIMIT)
        embed = embeds.board_embed(row, model, name, pending=pending, log=log,
                                   web_url=views.web_url(row))
        await replies.reply(interaction, embed=embed)

    manager = app_commands.Group(
        name='manager',
        description='Manage who may run matches in this server.')

    @manager.command(name='add',
                     description='Let a player manage this server’s matches.')
    @app_commands.guild_only()
    @app_commands.describe(member='The player to allow.')
    async def manager_add(self, interaction: discord.Interaction,
                          member: discord.Member) -> None:
        """Give a player the server's match permission."""
        await interaction.response.defer(ephemeral=True)
        guild = await db.guild_for(interaction)
        caller = await db.player_for(interaction.user)
        if not await db.run_db(core_permissions.is_guild_manager, guild,
                               caller):
            await replies.reply(interaction,
                                content=str(_('Only a manager of this server '
                                              'can do that.')))
            return
        target = await db.player_for(member)
        await db.run_db(core_permissions.grant_manager, guild, target)
        await replies.reply(interaction, content=str(
            _('%(name)s may now manage matches here.')
            % {'name': target.display_name}))

    @manager.command(
        name='remove',
        description='Stop a player managing this server’s matches.')
    @app_commands.guild_only()
    @app_commands.describe(member='The player to stop.')
    async def manager_remove(self, interaction: discord.Interaction,
                             member: discord.Member) -> None:
        """Withdraw a player's server match permission."""
        await interaction.response.defer(ephemeral=True)
        guild = await db.guild_for(interaction)
        caller = await db.player_for(interaction.user)
        if not await db.run_db(core_permissions.is_guild_manager, guild,
                               caller):
            await replies.reply(interaction,
                                content=str(_('Only a manager of this server '
                                              'can do that.')))
            return
        target = await db.player_for(member)
        if target.is_superuser:
            await replies.reply(interaction,
                                content=str(_('Superusers manage every '
                                              'server.')))
            return
        permissions = getattr(member, 'guild_permissions', None)
        if permissions is not None and permissions.manage_guild:
            await replies.reply(interaction, content=str(
                _('That player manages this server in Discord, so they keep '
                  'the permission.')))
            return
        removed = await db.run_db(core_permissions.revoke_manager, guild,
                                  target)
        message = (_('%(name)s may no longer manage matches here.')
                   if removed else
                   _('%(name)s does not manage matches here.'))
        await replies.reply(interaction, content=str(
            message % {'name': target.display_name}))


    async def _match(self, interaction: discord.Interaction,
                     raw: str | None) -> Match | None:
        """Return the match named, or answer the refusal and return None."""
        try:
            return await choices.resolve_match(interaction, raw)
        except errors.NoMatch as error:
            await replies.reply(interaction,
                                content=errors.refusal_text(error))
            return None

    async def cog_app_command_error(
            self, interaction: discord.Interaction,
            error: app_commands.AppCommandError) -> None:
        """Answer a command that raised something unexpected."""
        logger.exception('A /match command failed', exc_info=error)
        await replies.reply(interaction, content=str(_('That did not work.')))


async def setup(bot: commands.Bot) -> None:
    """Add the /match commands to the client."""
    await bot.add_cog(MatchCog(bot))



