"""Build the rows the service tests play with."""

from secrets import randbits
from uuid import uuid4

from core.models import Guild, Player
from games.models import UndoPolicy
from games.services import actions, matches
from games.services.projections import render_model


def make_guild(discord_id=None, name='Server'):
    return Guild.objects.create(
        discord_id=discord_id if discord_id is not None else randbits(60),
        name=name)


def make_player(username):
    unique = f'{username}-{uuid4().hex[:8]}'
    return Player.objects.create_user(username=unique,
                                  email=f'{unique}@example.com',
                                  password='secret')


def started_match(players=2, *, seed=5, undo_policy=UndoPolicy.SAFE,
                  slug='card-sample-game', options=None):
    """Return a started match and the players seated at it."""
    guild = make_guild()
    people = [make_player(f'player{index}') for index in range(players)]
    match = matches.create_match(
        guild=guild, channel_id=1, slug=slug, player=people[0],
        seats=players, seed=seed, undo_policy=undo_policy,
        options={'deck_rounds': 1} if options is None else options)
    for person in people[1:]:
        matches.join_match(match.pk, person)
    matches.start_match(match.pk, people[0])
    match.refresh_from_db()
    return match, people


def play_first(match, player):
    """Apply the first legal action of ``player`` and return the match."""
    option = render_model(match, player).actions[0]
    params = {param.key: param.options[0] for param in option.params}
    return actions.apply_action(match.pk, player, option.id, params)



