"""Resolve the values Discord sends against the choices the bot offered."""

from discord import Interaction, app_commands
from django.utils.translation import gettext_lazy as _

from games import registry
from bgb_engine.base import GameDefinition
from games.models import Match, MatchStatus
from games.services.errors import UnknownGame

from . import db, errors
from .limits import CHOICE_LIMIT, CHOICE_NAME_LIMIT


def game_choices(current: str) -> list[app_commands.Choice[str]]:
    """Return the installed games whose label matches what was typed."""
    wanted = current.strip().casefold()
    choices = []
    for definition in registry.available().values():
        label = f'{definition.name} ({definition.slug})'
        if not wanted or wanted in label.casefold():
            choices.append(app_commands.Choice(name=label[:CHOICE_NAME_LIMIT],
                                               value=definition.slug))
    return choices[:CHOICE_LIMIT]


def resolve_game(raw: str) -> GameDefinition:
    """Return the game named by slug, display name or autocomplete label."""
    wanted = raw.strip()
    for definition in registry.available().values():
        label = f'{definition.name} ({definition.slug})'
        if wanted.casefold() in (definition.slug.casefold(),
                                 definition.name.casefold(),
                                 label.casefold()):
            return definition
    raise UnknownGame(wanted)


def _game_name(match: Match) -> str:
    """Return the display name of the match's game."""
    try:
        return registry.get(match.slug).name
    except LookupError:
        return match.slug


def match_label(match: Match) -> str:
    """Return how a match is offered in autocomplete."""
    game = _game_name(match)
    if match.name:
        return (f'#{match.pk} {match.name} '
                f'({game}, {match.get_status_display()})')
    return f'#{match.pk} {game} ({match.get_status_display()})'


def open_matches(discord_guild_id: int, channel_id: int) -> list[Match]:
    """Return the matches of one channel that are still playable."""
    return list(Match.objects.filter(
        guild__discord_id=discord_guild_id, channel_id=channel_id,
        status__in=[MatchStatus.SETUP, MatchStatus.ACTIVE])
        .select_related('guild')
        .order_by('-created_at')[:CHOICE_LIMIT])


async def match_choices(interaction: Interaction,
                        current: str) -> list[app_commands.Choice[str]]:
    """Return the open matches of this channel whose label matches."""
    rows = await db.run_db(open_matches, interaction.guild_id or 0,
                           interaction.channel_id or 0)
    wanted = current.strip().casefold()
    return [app_commands.Choice(name=match_label(match)[:CHOICE_NAME_LIMIT],
                                value=str(match.pk))
            for match in rows
            if not wanted or wanted in match_label(match).casefold()][:CHOICE_LIMIT]


async def resolve_match(interaction: Interaction, raw: str | None) -> Match:
    """Return the match named, or the only open match of the channel.

    Seeding the caller's manager permission happens here, on every command.
    """
    await db.seed_managers(interaction)
    rows = await db.run_db(open_matches, interaction.guild_id or 0,
                           interaction.channel_id or 0)
    if raw is None:
        if not rows:
            raise errors.NoMatch(str(_('No match is open in this channel.')))
        if len(rows) > 1:
            raise errors.NoMatch(str(_('Several matches are open here; name '
                                       'the one you mean.')))
        return rows[0]
    wanted = raw.strip()
    if wanted.isdigit():
        match = await db.run_db(db.match_row, int(wanted),
                                interaction.guild_id or 0)
        if match is not None and match.channel_id == interaction.channel_id:
            return match
    for match in rows:
        labels = (str(match.pk), match_label(match).casefold(),
                  (match.name or match.slug).casefold(),
                  match.slug.casefold())
        if wanted.casefold() in labels:
            return match
    raise errors.NoMatch(str(_('That match is no longer open here.')))
