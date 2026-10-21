"""Embeds of a match, clipped to what Discord accepts."""

from collections.abc import Iterable
from typing import Any

import discord
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy as _n

from games.engine.base import RenderModel
from games.models import Match, MatchStatus, PendingChoice
from games.services.matches import match_title

CONTENT_LIMIT = 2000
TOTAL_LIMIT = 6000
EMBED_LIMIT = 10
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_LIMIT = 25
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FOOTER_LIMIT = 2048
RESERVE = 80

PLAYING = discord.Colour.blurple()
FINISHED = discord.Colour.dark_grey()
EMPTY = '(none)'
ELLIPSIS = '...'


def clip(text: Any, limit: int) -> str:
    """Return text trimmed to a limit, ending with an ellipsis."""
    value = str(text)
    if len(value) <= limit:
        return value
    return value[:limit - len(ELLIPSIS)].rstrip() + ELLIPSIS


def size(embed: discord.Embed) -> int:
    """Return the number of characters Discord counts for an embed."""
    total = len(embed.title or '') + len(embed.description or '')
    footer = embed.footer
    if footer is not None:
        text = footer.text
        if text:
            total += len(text)
    for field in embed.fields:
        total += len(field.name or '') + len(field.value or '')
    return total


def fit(embed: discord.Embed, budget: int = TOTAL_LIMIT) -> discord.Embed:
    """Trim an embed to the limits, dropping fields the budget cannot hold."""
    if embed.title:
        embed.title = clip(embed.title, TITLE_LIMIT)
    if embed.description:
        embed.description = clip(embed.description, DESCRIPTION_LIMIT)
    footer = embed.footer
    footer_text = footer.text if footer is not None else None
    if footer_text:
        embed.set_footer(text=clip(footer_text, FOOTER_LIMIT))
    fields = [(clip(field.name, FIELD_NAME_LIMIT),
               clip(field.value, FIELD_VALUE_LIMIT), field.inline)
              for field in list(embed.fields)[:FIELD_LIMIT]]
    embed.clear_fields()
    used = size(embed)
    for name, value, inline in fields:
        if embed.fields and used + len(name) + len(value) > budget - RESERVE:
            break
        embed.add_field(name=name, value=value, inline=inline)
        used += len(name) + len(value)
    return embed


def kept_lines(lines: list[str],
               limit: int = FIELD_VALUE_LIMIT - RESERVE) -> tuple[list[str], int]:
    """Return how many lines fit, and how many were left out."""
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if kept and used + len(line) + 1 > limit:
            return kept, len(lines) - index
        kept.append(line)
        used += len(line) + 1
    return kept, 0


def block(lines: list[str], left: int = 0) -> str:
    """Return lines as one field value, noting the ones left out."""
    text = '\n'.join(lines)
    if left:
        text += '\n' + str(_('%(ellipsis)sand %(count)s more.') % {'ellipsis': ELLIPSIS, 'count': left})
    return clip(text, FIELD_VALUE_LIMIT)


def seat_lines(model: RenderModel) -> list[str]:
    """Return one line per seat, with its counters and hidden cards."""
    lines = []
    for seat in model.seats:
        marks = []
        if seat.is_active:
            marks.append(str(_('playing')))
        if seat.eliminated:
            marks.append(str(_('out')))
        suffix = f' ({", ".join(marks)})' if marks else ''
        details = []
        if seat.counters:
            details.append(', '.join(f'{key}: {value}'
                                     for key, value in seat.counters.items()))
        if seat.hidden_cards:
            details.append(str(_n('%(count)s card', '%(count)s cards',
                                  seat.hidden_cards)
                               % {'count': seat.hidden_cards}))
        detail = f' ({", ".join(details)})' if details else ''
        lines.append(f'**{seat.label}**{suffix}{detail}')
    return lines


def zone_lines(model: RenderModel) -> list[str]:
    """Return one line per zone, with its cards and hidden count."""
    lines = []
    for zone in model.zones:
        parts = [card.label for card in zone.cards]
        if zone.hidden_count is not None:
            parts.append(str(_n('%(count)s hidden', '%(count)s hidden',
                                zone.hidden_count)
                             % {'count': zone.hidden_count}))
        lines.append(f'**{zone.label}**: ' + (', '.join(parts) or EMPTY))
    return lines


def score_lines(scores: Iterable[dict[str, Any]]) -> list[str]:
    """Return one line per score row, whatever fields the game keeps."""
    lines = []
    for row in scores:
        name = row.get('name')
        if not name:
            name = _('Seat %(number)s') % {
                'number': int(row.get('position', 0)) + 1}
        details = ', '.join(f'{key}: {value}' for key, value in row.items()
                            if key not in ('name', 'position'))
        lines.append(f'{name}: {details}' if details else str(name))
    return lines


def private_lines(model: RenderModel) -> list[str]:
    """Return the private zones one seat may see, in display order."""
    lines = []
    for zone in model.zones:
        if not zone.private:
            continue
        parts = [card.label for card in zone.cards]
        if zone.hidden_count is not None:
            parts.append(str(_n('%(count)s hidden', '%(count)s hidden',
                                zone.hidden_count)
                             % {'count': zone.hidden_count}))
        lines.append(f'**{zone.label}**: ' + (', '.join(parts) or EMPTY))
    if not lines:
        lines.append(str(_('No private information in this game.')))
    return lines


def board_embed(match: Match, model: RenderModel, game_name: str,
                pending: PendingChoice | None = None,
                log: Iterable[dict[str, Any]] = (),
                web_url: str = '') -> discord.Embed:
    """Return the public board of a match, as Discord shows it."""
    embed = discord.Embed(
        title=clip(match_title(match, game_name), TITLE_LIMIT),
        description=clip(model.status, DESCRIPTION_LIMIT),
        colour=PLAYING if match.status == MatchStatus.ACTIVE else FINISHED,
        url=web_url or None)
    seats = seat_lines(model)
    if seats:
        kept, left = kept_lines(seats)
        embed.add_field(name=str(_('Seats')), value=block(kept, left),
                        inline=False)
    zones = zone_lines(model)
    if zones:
        kept, left = kept_lines(zones)
        embed.add_field(name=str(_('Table')), value=block(kept, left),
                        inline=False)
    if pending is not None:
        who = (pending.seat.display_name
               or (pending.seat.player.display_name
                   if pending.seat.player else ''))
        if not who:
            who = str(_('Seat %(number)s') % {
                'number': pending.seat.position + 1})
        embed.add_field(name=str(_('Waiting for')),
                        value=clip(f'{who}: {pending.label}',
                                   FIELD_VALUE_LIMIT), inline=False)
    moves = [str(entry.get('text', '')) for entry in log]
    if moves:
        kept, left = kept_lines(moves)
        embed.add_field(name=str(_('Last moves')), value=block(kept, left),
                        inline=False)
    embed.set_footer(text=clip(f'Match #{match.pk}, rules v{match.rules_version}',
                               FOOTER_LIMIT))
    return fit(embed)


def recap_embed(match: Match, summary: dict[str, Any], game_name: str,
                web_url: str = '') -> discord.Embed:
    """Return the final scores and the summary of a finished match."""
    embed = discord.Embed(
        title=clip(match_title(match, game_name), TITLE_LIMIT),
        description=str(_('Game over.')),
        colour=FINISHED, url=web_url or None)
    lines = score_lines(summary.get('scores') or [])
    if lines:
        kept, left = kept_lines(lines)
        embed.add_field(name=str(_('Final scores')), value=block(kept, left),
                        inline=False)
    embed.set_footer(text=clip(f'Match #{match.pk}, rules v{match.rules_version}',
                               FOOTER_LIMIT))
    return fit(embed)


def private_embed(match: Match, model: RenderModel, game_name: str,
                  web_url: str = '') -> discord.Embed:
    """Return the private information of one seat, and what it is waiting for."""
    lines = private_lines(model)
    if model.pending is not None:
        lines.append(str(_('Waiting for: %(label)s') % {
            'label': model.pending.label}))
    embed = discord.Embed(
        title=clip(f'{match_title(match, game_name)} (private info)',
                   TITLE_LIMIT),
        description=clip('\n'.join(lines), DESCRIPTION_LIMIT),
        colour=PLAYING, url=web_url or None)
    embed.add_field(name=str(_('Status')),
                    value=clip(model.status, FIELD_VALUE_LIMIT))
    embed.set_footer(text=clip(f'Match #{match.pk}, rules v{match.rules_version}',
                               FOOTER_LIMIT))
    return fit(embed)


def hand_embed(match: Match, model: RenderModel, game_name: str,
               web_url: str = '') -> discord.Embed:
    """Compatibility alias for the old hand embed."""
    return private_embed(match, model, game_name, web_url)
