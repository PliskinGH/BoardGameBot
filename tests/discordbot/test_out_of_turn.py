"""Tests for pending seats in the Discord board and panels."""

import asyncio
from unittest import mock

from django.test import TransactionTestCase

from discordbot import outbox_worker, views
from games.models import OutboxMessage
from games.services import actions, matches, outbox
from tests.discordbot.fakes import (FakeBot, discord_player,
                                     interaction_for)
from tests.factories import make_guild
from tests.games.pending_game import ensure_registered
from tests.support import NoDiscordMixin

NONCE = 'abcdef'


def pending_match():
    """Return a started reaction match and its players."""
    ensure_registered()
    guild = make_guild()
    people = [discord_player(42, 'user42'), discord_player(43, 'user43')]
    match = matches.create_match(
        guild=guild, channel_id=100, slug='pending-reaction-game',
        player=people[0], seats=2)
    matches.join_match(match.pk, people[1])
    matches.start_match(match.pk, people[0])
    match.refresh_from_db()
    return match, people


class OutOfTurnViewTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = pending_match()
        OutboxMessage.objects.filter(match=self.match).delete()

    def open_reaction(self):
        option = views.render_model(self.match, self.players[0]).actions[0]
        self.match = actions.apply_action(
            self.match.pk, self.players[0], option.id)
        return self.match

    def test_only_the_pending_seat_is_needed_during_a_reaction(self):
        self.open_reaction()

        self.assertEqual(views.needed_seats(self.match), {1})
        self.assertEqual(views.pending_choice(self.match).seat.position, 1)

    def test_the_active_seat_is_needed_again_after_the_choice(self):
        self.open_reaction()
        self.match = actions.apply_action(
            self.match.pk, self.players[1], 'react', {'answer': 'accept'})

        self.assertEqual(views.needed_seats(self.match), {0})

    def test_the_pending_player_can_open_their_panel(self):
        self.open_reaction()
        interaction = interaction_for(self.players[1], self.match)

        asyncio.run(views.open_panel(interaction, self.match.pk))

        self.assertTrue(interaction.response.messages)
        self.assertIsNotNone(interaction.response.messages[0].get('view'))

    def test_the_pending_player_can_read_their_private_prompt(self):
        self.open_reaction()
        interaction = interaction_for(self.players[1], self.match)

        asyncio.run(views.show_private(interaction, self.match.pk))

        messages = interaction.response.messages
        self.assertTrue(messages)
        self.assertIn('Waiting for', messages[0]['embed'].description)

    def test_the_pending_player_can_apply_from_the_panel(self):
        self.open_reaction()
        player = self.players[1]
        interaction = interaction_for(player, self.match)
        model = views.render_model(self.match, player)
        token = views.panel_token(
            self.match, model, views.viewer_position(self.match, player))

        asyncio.run(views.apply_choice(
            interaction, self.match.pk, token, NONCE, 0, {0: 0}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 2)
        self.assertFalse(self.match.pending_choices.filter(
            resolved_at__isnull=True).exists())

    def test_a_new_pending_seat_replaces_and_pings_the_board(self):
        send = mock.AsyncMock(return_value=900)
        edit = mock.AsyncMock()
        delete = mock.AsyncMock()
        self.open_reaction()
        outbox.enqueue(self.match)

        with mock.patch.object(outbox_worker.discord_api,
                               'send_embed', send), \
                mock.patch.object(outbox_worker.discord_api,
                                  'edit_embed', edit), \
                mock.patch.object(outbox_worker.discord_api,
                                  'delete_message', delete):
            asyncio.run(outbox_worker.run_once(FakeBot()))

        self.match.refresh_from_db()
        self.assertEqual(self.match.board_message_id, 900)
        self.assertEqual(self.match.last_needed_seats, [1])
        send.assert_awaited_once()
        self.assertNotIn('<@42>', send.await_args.kwargs['content'])
        self.assertIn('<@43>', send.await_args.kwargs['content'])
        edit.assert_not_awaited()
        delete.assert_not_awaited()
