"""Stand-ins for the Discord objects the bot touches, and an inline ORM."""

from typing import Any

import discord

from core.models import DiscordAccount, Player
from games.models import Match
from games.services import matches
from tests.factories import make_guild


class FakePermissions:
    """The guild permissions an interaction carries."""

    def __init__(self, manage_guild: bool = False) -> None:
        self.manage_guild = manage_guild


class FakeUser:
    """A Discord account, as an interaction carries it."""

    def __init__(self, user_id: int = 42, name: str = 'wendy', *,
                 display_name: str | None = None,
                 manage_guild: bool = False) -> None:
        self.id = user_id
        self.name = name
        self.display_name = display_name or name
        self.guild_permissions = FakePermissions(manage_guild)


class FakeGuild:
    """A Discord server, as an interaction carries it."""

    def __init__(self, guild_id: int = 1, name: str = 'Server') -> None:
        self.id = guild_id
        self.name = name


class FakeResponse:
    """Records how a flow answered, and whether it answered yet."""

    def __init__(self) -> None:
        self.deferred: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.modals: list[Any] = []
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, **kwargs: Any) -> None:
        self._done = True
        self.deferred.append(kwargs)

    async def send_message(self, **kwargs: Any) -> None:
        self._done = True
        self.messages.append(kwargs)

    async def edit_message(self, **kwargs: Any) -> None:
        self._done = True
        self.edits.append(kwargs)

    async def send_modal(self, modal: Any) -> None:
        self._done = True
        self.modals.append(modal)


class FakeFollowup:
    """Records the messages a deferred flow sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class FakeInteraction:
    """What a command or a component handler reads from Discord."""

    def __init__(self, *, user: FakeUser | None = None,
                 guild: FakeGuild | None = None,
                 channel_id: int = 100) -> None:
        self.user = user or FakeUser()
        self.guild = guild or FakeGuild()
        self.guild_id = self.guild.id
        self.channel_id = channel_id
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class FakeMessage:
    """A message the bot may edit or delete."""

    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.edits: list[dict[str, Any]] = []
        self.deleted = False

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    async def delete(self) -> None:
        self.deleted = True


class FakeChannel:
    """A channel the worker posts in."""

    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.messages: list[FakeMessage] = []
        self.by_id: dict[int, FakeMessage] = {}

    async def send(self, **kwargs: Any) -> FakeMessage:
        message = FakeMessage(500 + len(self.messages))
        self.messages.append(message)
        self.by_id[message.id] = message
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        message = self.by_id.get(message_id)
        if message is None:
            message = FakeMessage(message_id)
            self.by_id[message_id] = message
        return message


class FakeBot:
    """A client that only resolves its channel."""

    def __init__(self, channel: FakeChannel | None = None) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channel

    async def fetch_channel(self, channel_id: int) -> FakeChannel:
        if self.channel is None:
            raise AssertionError('That channel is not cached.')
        return self.channel


def discord_player(user_id: int, name: str) -> Player:
    """Return the player row a fake Discord account resolves to."""
    return Player.objects.from_discord(DiscordAccount(id=user_id, name=name))


def bot_match(user_ids=(42, 43), *, channel_id: int = 100):
    """Return a started match whose players the fakes resolve to."""
    guild = make_guild()
    people = [discord_player(user_id, f'user{user_id}')
              for user_id in user_ids]
    match = matches.create_match(guild=guild, channel_id=channel_id,
                                 slug='card-sample-game', player=people[0],
                                 options={'deck_rounds': 1})
    for person in people[1:]:
        matches.join_match(match.pk, person)
    matches.start_match(match.pk, people[0])
    match.refresh_from_db()
    return match, people


def interaction_for(player: Player, match: Match, *,
                    channel_id: int | None = None,
                    manage_guild: bool = False,
                    display_name: str | None = None) -> FakeInteraction:
    """Return an interaction acting as the Discord user behind ``player``."""
    return FakeInteraction(
        user=FakeUser(player.discord_user_id or 0,
                      player.discord_name or player.username,
                      display_name=display_name,
                      manage_guild=manage_guild),
        guild=FakeGuild(match.guild.discord_id, match.guild.name),
        channel_id=channel_id if channel_id is not None else match.channel_id)


def setup_match(channel_id: int = 100):
    """Return a match waiting for players, and the players it will seat."""
    guild = make_guild()
    people = [discord_player(42, 'user42'), discord_player(43, 'user43')]
    match = matches.create_match(guild=guild, channel_id=channel_id,
                                 slug='card-sample-game', player=people[0],
                                 options={'deck_rounds': 1})
    return match, people[0], people[1]


def mark_hand(match: Match, position: int, label: str) -> None:
    """Give a seat a card with a label no other view may show."""
    seat = match.seats.get(position=position)
    seat.private_state = {
        **seat.private_state,
        'hand': [{'id': f'sentinel-{position}', 'label': label, 'value': 1},
                 *seat.private_state['hand']],
    }
    seat.save(update_fields=['private_state'])
