"""The controls a match is played with, and the state they re-resolve."""

import hashlib
import re
import secrets
from typing import Any

import discord
from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.models import Player
from bgb_engine.base import ActionOption, IllegalAction, Param, RenderModel
from games.models import Match, MatchStatus, PendingChoice
from games.services import actions, matches, undo
from games.services.contexts import definition_for
from games.services.errors import ServiceError
from games.services.projections import render_model, viewer_position

from . import db, embeds, errors, replies
from .limits import (ACTION_LABEL_LIMIT, BUTTON_LABEL_LIMIT,
                     CHOICE_LIMIT, LABEL_LIMIT, LAYOUT_TEXT_LIMIT,
                     MODAL_TITLE_LIMIT, OPTION_LABEL_LIMIT,
                     PLACEHOLDER_LIMIT)

# A panel fingerprint: 6 bytes, 12 hex characters.
TOKEN_SIZE = 6
TOKEN_HEX_LENGTH = TOKEN_SIZE * 2
# A per-opening panel or modal tail: 3 bytes, 6 hex characters.
NONCE_SIZE = 3
NONCE_HEX_LENGTH = NONCE_SIZE * 2
# The id arithmetic is bounded well below Discord's 100 characters.
ID_LIMIT = 100
# Actions one panel offers; the sixth row does not exist.
MAX_ACTIONS = 5


def panel_token(match: Match, model: RenderModel,
                position: int | None) -> str:
    """Return a short fingerprint of the panel this player would see."""
    payload = [(option.id, option.enabled,
                [(param.key, param.kind,
                  tuple(str(value) for value in param.options),
                  tuple(param.labels))
                 for param in option.params])
               for option in model.actions]
    raw = repr((match.version, position, payload)).encode()
    return hashlib.blake2s(raw, digest_size=TOKEN_SIZE).hexdigest()


def board_id(pk: int, action: str) -> str:
    """Return the custom id of a public board button."""
    return _checked(f'match:{pk}:{action}')


def panel_nonce() -> str:
    """Return a random tail for one non-persistent control."""
    return secrets.token_hex(NONCE_SIZE)


def panel_id(pk: int, token: str, nonce: str, kind: str,
             *parts: int | str) -> str:
    """Return the custom id of one panel component."""
    tail = ':'.join(str(part) for part in parts)
    return _checked(f'match:{pk}:{token}:{nonce}:{kind}:{tail}')


def _checked(custom_id: str) -> str:
    """Refuse to build an id Discord would reject."""
    if len(custom_id) > ID_LIMIT:
        raise ValueError(f'custom id too long: {custom_id!r}')
    return custom_id


def game_name(match: Match) -> str:
    """Return the display name of the game of a match."""
    return definition_for(match).name


def web_url(match: Match) -> str:
    """Return the web display of a match, or empty when none is configured."""
    if not settings.WEB_BASE_URL:
        return ''
    return (f"{settings.WEB_BASE_URL.rstrip('/')}"
            + reverse('board:match',
                      args=[match.guild.discord_id, match.pk]))


def pending_choice(match: Match) -> PendingChoice | None:
    """Return the choice a seat still has to answer, if any."""
    return (match.pending_choices.filter(resolved_at__isnull=True)
            .select_related('seat__player').order_by('pk').first())

def needed_seats(match: Match) -> set[int]:
    """Return the seats that still have to act in this match.

    An open choice takes precedence: while any choice is pending, only its
    seat is needed; otherwise the active seat is needed.
    """
    if match.status != MatchStatus.ACTIVE:
        return set()
    pending = set(
        match.pending_choices.filter(resolved_at__isnull=True)
        .values_list('seat__position', flat=True))
    if pending:
        return pending
    active = match.active_seat
    return {active.position} if active is not None else set()


def turn_mentions(match: Match, positions: set[int]) -> str:
    """Return mentions for newly needed seats, or an empty string."""
    mentions = []
    seats = {seat.position: seat
             for seat in match.seats.select_related('player')}
    for position in sorted(positions):
        seat = seats.get(position)
        if seat is None or seat.player is None:
            continue
        if seat.player.discord_user_id:
            mentions.append(f'<@{seat.player.discord_user_id}>')
    if not mentions:
        return ''
    title = matches.match_title(match, definition_for(match).name)
    return f'{" ".join(mentions)} The table is waiting for you in {title}.'


def _display_name(interaction: discord.Interaction) -> str:
    """Return the caller's server display name."""
    return (getattr(interaction.user, 'display_name', '')
            or getattr(interaction.user, 'name', ''))




def board_view(match: Match) -> discord.ui.View:
    """Return the persistent controls of the public board."""
    view = discord.ui.View(timeout=None)
    private = 'private' in definition_for(match).capabilities
    if match.status == MatchStatus.SETUP:
        view.add_item(MatchJoinButton(match.pk))
        view.add_item(MatchLeaveButton(match.pk))
        view.add_item(MatchStartButton(match.pk))
        view.add_item(MatchCloseButton(match.pk))
    elif match.status == MatchStatus.ACTIVE:
        view.add_item(MatchActButton(match.pk))
        if private:
            view.add_item(MatchPrivateButton(match.pk))
        if match.position:
            view.add_item(MatchUndoButton(match.pk))
        view.add_item(MatchCloseButton(match.pk))
    elif private:
        view.add_item(MatchPrivateButton(match.pk))
    return view


async def _load(interaction: discord.Interaction,
                pk: int) -> tuple[Match, Player] | None:
    """Return the match and the caller, or refuse and return None."""
    match = await db.run_db(db.match_row, pk, interaction.guild_id or 0)
    if match is None:
        await replies.reply(
            interaction,
            content=str(_('That match does not exist here any more.')))
        return None
    player = await db.player_for(interaction.user)
    await db.run_db(matches.remember_seat_name, match.pk, player,
                    _display_name(interaction))
    return match, player


async def open_panel(interaction: discord.Interaction, pk: int) -> None:
    """Show the caller the moves they may make right now."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    if match.status != MatchStatus.ACTIVE:
        await replies.reply(interaction,
                            content=str(_('This match is not being played.')))
        return
    position = await db.run_db(viewer_position, match, player)
    if position is None:
        await replies.reply(interaction,
                            content=str(_('You hold no seat in this match.')))
        return
    model = await db.run_db(render_model, match, player)
    if not model.actions:
        await replies.reply(interaction,
                            content=str(_('It is not your turn.')))
        return
    token = panel_token(match, model, position)
    nonce = panel_nonce()
    await replies.reply(interaction,
                        view=panel_view(match, model, token, nonce))


async def show_private(interaction: discord.Interaction, pk: int) -> None:
    """Show the private information of the caller's seat."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    if await db.run_db(viewer_position, match, player) is None:
        await replies.reply(interaction,
                            content=str(_('You hold no seat in this match.')))
        return
    model = await db.run_db(render_model, match, player)
    await replies.reply(
        interaction,
        embed=embeds.private_embed(match, model,
                                   await db.run_db(game_name, match),
                                   web_url(match)))


async def show_hand(interaction: discord.Interaction, pk: int) -> None:
    """Compatibility alias for the old hand command."""
    await show_private(interaction, pk)


async def undo_match(interaction: discord.Interaction, pk: int, *,
                     force: bool = False, reason: str = '') -> None:
    """Undo the live action of the caller, if the policy allows it."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    try:
        await db.run_db(undo.undo_last_action, match.pk, player,
                        force=force, reason=reason)
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    await replies.reply(interaction,
                        content=str(_('Undone. The board follows.')))


async def join_match(interaction: discord.Interaction, pk: int) -> None:
    """Seat the caller at the first free seat."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    try:
        seat = await db.run_db(matches.join_match, match.pk, player,
                               seat_name=_display_name(interaction))
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    await replies.reply(interaction, content=str(
        _('Seat %(number)s is yours.') % {'number': seat.position + 1}))


async def leave_match(interaction: discord.Interaction, pk: int) -> None:
    """Free the caller's seat before the match starts."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    try:
        await db.run_db(matches.leave_match, match.pk, player)
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    await replies.reply(interaction, content=str(_('Your seat is free.')))


async def start_match(interaction: discord.Interaction, pk: int) -> None:
    """Start the match when every seat is taken."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    try:
        await db.run_db(matches.start_match, match.pk, player,
                        seat_name=_display_name(interaction))
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    await replies.reply(interaction, content=str(_('The match started.')))


async def close_match(interaction: discord.Interaction, pk: int) -> None:
    """Close the match as its host or a manager."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    try:
        await db.run_db(matches.close_match, match.pk, player)
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    await replies.reply(interaction, content=str(_('The match is closed.')))


class MatchActButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                     template=r'match:(?P<pk>\d+):act'):
    """Open the private move panel of the caller."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Take a turn')), style=discord.ButtonStyle.primary,
            custom_id=board_id(pk, 'act')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchActButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await open_panel(interaction, self.pk)


class MatchHandButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                      template=r'match:(?P<pk>\d+):hand'):
    """Compatibility button for the old hand custom id."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Private info')), style=discord.ButtonStyle.secondary,
            custom_id=board_id(pk, 'hand')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchHandButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await show_hand(interaction, self.pk)


class MatchUndoButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                      template=r'match:(?P<pk>\d+):undo'):
    """Undo the live action of the caller, when the policy allows it."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Undo')), style=discord.ButtonStyle.secondary,
            custom_id=board_id(pk, 'undo')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchUndoButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await undo_match(interaction, self.pk)


class MatchJoinButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                      template=r'match:(?P<pk>\d+):join'):
    """Seat the caller before the match starts."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Join')), style=discord.ButtonStyle.primary,
            custom_id=board_id(pk, 'join')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchJoinButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await join_match(interaction, self.pk)


class MatchLeaveButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                       template=r'match:(?P<pk>\d+):leave'):
    """Free the caller's seat before the match starts."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Leave')), style=discord.ButtonStyle.secondary,
            custom_id=board_id(pk, 'leave')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchLeaveButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await leave_match(interaction, self.pk)


class MatchStartButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                       template=r'match:(?P<pk>\d+):start'):
    """Start the match when every seat is taken."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Start')), style=discord.ButtonStyle.success,
            custom_id=board_id(pk, 'start')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchStartButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await start_match(interaction, self.pk)


class MatchCloseButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                       template=r'match:(?P<pk>\d+):close'):
    """Close the match as its host or a manager."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Close')), style=discord.ButtonStyle.danger,
            custom_id=board_id(pk, 'close')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchCloseButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await close_match(interaction, self.pk)


class MatchPrivateButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                         template=r'match:(?P<pk>\d+):private'):
    """Show the caller the private information of their seat."""

    def __init__(self, pk: int) -> None:
        super().__init__(discord.ui.Button(
            label=str(_('Private info')), style=discord.ButtonStyle.secondary,
            custom_id=board_id(pk, 'private')))
        self.pk = pk

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchPrivateButton':
        return cls(int(match['pk']))

    async def callback(self, interaction: discord.Interaction) -> None:
        await show_private(interaction, self.pk)


class MatchActionButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                        template=rf'match:(?P<pk>\d+):(?P<token>[0-9a-f]{{{TOKEN_HEX_LENGTH}}}):(?P<nonce>[0-9a-f]{{{NONCE_HEX_LENGTH}}}):do:(?P<index>\d+)'):
    """Apply an action that needs no argument."""

    def __init__(self, pk: int, token: str, nonce: str, index: int,
                 label: str) -> None:
        super().__init__(discord.ui.Button(
            label=embeds.clip(label or '\u200b', BUTTON_LABEL_LIMIT),
            style=discord.ButtonStyle.primary,
            custom_id=panel_id(pk, token, nonce, 'do', index)))
        self.pk = pk
        self.token = token
        self.nonce = nonce
        self.index = index

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchActionButton':
        return cls(int(match['pk']), match['token'], match['nonce'],
                   int(match['index']), '')

    async def callback(self, interaction: discord.Interaction) -> None:
        await apply_choice(interaction, self.pk, self.token, self.nonce,
                           self.index, {})


class MatchParamSelect(discord.ui.DynamicItem[discord.ui.Select[Any]],
                       template=rf'match:(?P<pk>\d+):(?P<token>[0-9a-f]{{{TOKEN_HEX_LENGTH}}}):(?P<nonce>[0-9a-f]{{{NONCE_HEX_LENGTH}}}):pick:(?P<action>\d+):(?P<param>\d+)'):
    """Apply an action from the option the player picks."""

    def __init__(self, pk: int, token: str, nonce: str, action_index: int,
                 param_index: int, *, placeholder: str = '',
                 options: list[discord.SelectOption] | None = None) -> None:
        super().__init__(discord.ui.Select(
            custom_id=panel_id(pk, token, nonce, 'pick', action_index,
                               param_index),
            placeholder=embeds.clip(placeholder or _('Choose'), PLACEHOLDER_LIMIT),
            options=options or [discord.SelectOption(label='\u200b',
                                                     value='0')]))
        self.pk = pk
        self.token = token
        self.nonce = nonce
        self.action_index = action_index
        self.param_index = param_index

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchParamSelect':
        return cls(int(match['pk']), match['token'], match['nonce'],
                   int(match['action']), int(match['param']))

    async def callback(self, interaction: discord.Interaction) -> None:
        values = self.item.values
        if not values:
            return
        await apply_choice(interaction, self.pk, self.token, self.nonce,
                           self.action_index,
                           {self.param_index: int(values[0])})


class MatchFormButton(discord.ui.DynamicItem[discord.ui.Button[Any]],
                      template=rf'match:(?P<pk>\d+):(?P<token>[0-9a-f]{{{TOKEN_HEX_LENGTH}}}):(?P<nonce>[0-9a-f]{{{NONCE_HEX_LENGTH}}}):form:(?P<index>\d+)'):
    """Open the form of an action that needs several arguments."""

    def __init__(self, pk: int, token: str, nonce: str, index: int,
                 label: str, option: ActionOption | None = None,
                 model: RenderModel | None = None) -> None:
        super().__init__(discord.ui.Button(
            label=embeds.clip(label or '\u200b', BUTTON_LABEL_LIMIT),
            style=discord.ButtonStyle.secondary,
            custom_id=panel_id(pk, token, nonce, 'form', index)))
        self.pk = pk
        self.token = token
        self.nonce = nonce
        self.index = index
        self.option = option
        self.model = model

    @classmethod
    async def from_custom_id(
            cls, interaction: discord.Interaction,
            item: discord.ui.Item[Any],
            match: re.Match[str]) -> 'MatchFormButton':
        return cls(int(match['pk']), match['token'], match['nonce'],
                   int(match['index']), '')

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.option is None or self.model is None:
            await replies.reply(interaction, content=_stale())
            return
        await interaction.response.send_modal(
            ParamModal(self.pk, self.token, self.nonce, panel_nonce(),
                       self.index, self.option, self.model))


class ParamModal(discord.ui.Modal):
    """Ask for every argument of an action that needs several."""

    def __init__(self, pk: int, token: str, nonce: str, modal_nonce: str,
                 action_index: int, option: ActionOption,
                 model: RenderModel) -> None:
        super().__init__(
            title=embeds.clip(option.label, MODAL_TITLE_LIMIT),
            custom_id=panel_id(pk, token, nonce, 'modal', action_index,
                               modal_nonce))
        self.pk = pk
        self.token = token
        self.nonce = nonce
        self.action_index = action_index
        self.selects: list[discord.ui.Select[Any]] = []
        for param_index, param in enumerate(option.params):
            select: discord.ui.Select[Any] = discord.ui.Select(
                custom_id=f'p:{param_index}',
                placeholder=embeds.clip(param.label, PLACEHOLDER_LIMIT),
                options=parameter_options(model, param))
            label = option.label if len(option.params) == 1 else param.label
            self.add_item(discord.ui.Label(
                text=embeds.clip(label, LABEL_LIMIT), component=select))
            self.selects.append(select)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = {index: int(select.values[0])
                  for index, select in enumerate(self.selects)
                  if select.values}
        await apply_choice(interaction, self.pk, self.token, self.nonce,
                           self.action_index, values)


def _stale() -> str:
    """Return the sentence for a panel that no longer matches the table."""
    return str(_('That menu is out of date; run /match act again.'))


def parameter_options(model: RenderModel,
                      param: Param) -> list[discord.SelectOption]:
    """Return the options of one argument, labelled from the viewer's model."""
    hand = next((zone for zone in model.zones if zone.private), None)
    cards = {card.id: card.label for card in hand.cards} if hand else {}
    seats = {seat.position: seat.label for seat in model.seats}
    options = []
    for index, value in enumerate(param.options[:CHOICE_LIMIT]):
        if index < len(param.labels):
            label = param.labels[index]
        else:
            label = str(value)
            if param.kind == 'card':
                label = cards.get(str(value), label)
            elif param.kind == 'seat' and isinstance(value, int):
                label = seats.get(value, label)
        options.append(discord.SelectOption(
            label=embeds.clip(label, OPTION_LABEL_LIMIT), value=str(index)))
    return options


def panel_view(match: Match, model: RenderModel,
               token: str, nonce: str) -> discord.ui.LayoutView:
    """Return the private moves panel of one player."""
    view = discord.ui.LayoutView(timeout=None)
    lines = embeds.private_lines(model)
    lines.append(str(_('Status: %(status)s') % {'status': model.status}))
    view.add_item(discord.ui.TextDisplay(
        embeds.clip('\n'.join(lines), LAYOUT_TEXT_LIMIT)))
    for index, option in enumerate(model.actions[:MAX_ACTIONS]):
        if not option.params:
            view.add_item(discord.ui.ActionRow(
                MatchActionButton(match.pk, token, nonce, index,
                                  option.label)))
        elif len(option.params) == 1:
            param = option.params[0]
            view.add_item(discord.ui.TextDisplay(
                f'**{embeds.clip(option.label, ACTION_LABEL_LIMIT)}**'))
            view.add_item(discord.ui.ActionRow(MatchParamSelect(
                match.pk, token, nonce, index, 0, placeholder=param.label,
                options=parameter_options(model, param))))
        else:
            view.add_item(discord.ui.ActionRow(MatchFormButton(
                match.pk, token, nonce, index, option.label, option=option,
                model=model)))
    return view


async def apply_choice(interaction: discord.Interaction, pk: int, token: str,
                       nonce: str,
                       action_index: int, values: dict[int, int]) -> None:
    """Apply one option of a panel, after checking every index again."""
    loaded = await _load(interaction, pk)
    if loaded is None:
        return
    match, player = loaded
    position = await db.run_db(viewer_position, match, player)
    model = await db.run_db(render_model, match, player)
    if (position is None or panel_token(match, model, position) != token
            or not 0 <= action_index < len(model.actions)):
        await replies.reply(interaction, content=_stale())
        return
    option = model.actions[action_index]
    params: dict[str, Any] = {}
    for param_index, value_index in values.items():
        if not 0 <= param_index < len(option.params):
            await replies.reply(interaction, content=_stale())
            return
        param = option.params[param_index]
        if not 0 <= value_index < len(param.options):
            await replies.reply(interaction, content=_stale())
            return
        params[param.key] = param.options[value_index]
    try:
        match = await db.run_db(actions.apply_action, match.pk, player,
                                option.id, params, match.version)
    except (ServiceError, IllegalAction) as error:
        await replies.reply(interaction, content=errors.refusal_text(error))
        return
    model = await db.run_db(render_model, match, player)
    await interaction.response.edit_message(
        view=panel_view(match, model,
                        panel_token(match, model, position), nonce))




