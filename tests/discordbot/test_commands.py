"""Tests for the /match commands."""

import asyncio
from unittest import mock

from django.test import TransactionTestCase, override_settings

from core import permissions
from discordbot.choices import match_label
from discordbot.cogs.match import MatchCog, game_autocomplete, match_autocomplete
from bgb_engine.examples.card_sample.definition import CardSampleGame
from games.models import Match, MatchStatus, UndoPolicy
from games.services import matches
from tests.discordbot.fakes import (FakeGuild, FakeInteraction, FakeUser,
                                    bot_match, discord_player, interaction_for,
                                    mark_hand, setup_match)
from tests.factories import play_first
from tests.support import NoDiscordMixin


def run(command, interaction, *args, **kwargs):
    """Run one slash command the way Discord would."""
    cog = MatchCog(mock.Mock())
    asyncio.run(command.callback(cog, interaction, *args, **kwargs))


class NewCommandTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.interaction = FakeInteraction(user=FakeUser(42, 'user42'),
                                           guild=FakeGuild(7, 'Seven'),
                                           channel_id=100)

    def test_it_opens_a_match_in_the_channel(self):
        run(MatchCog.new, self.interaction, 'card-sample-game', None, UndoPolicy.SAFE)

        match = Match.objects.get()
        self.assertEqual(match.channel_id, 100)
        self.assertEqual(match.guild.discord_id, 7)
        self.assertEqual(match.seats.get(position=0).player.discord_user_id,
                         42)
        self.assertTrue(match.outbox.filter(kind='board_update').exists())
        self.assertIn('opened',
                      self.interaction.followup.sent[0]['content'])

    def test_it_records_the_name_and_the_server_name(self):
        self.interaction = FakeInteraction(
            user=FakeUser(42, 'user42', display_name='Wendy'),
            guild=FakeGuild(7, 'Seven'), channel_id=100)

        run(MatchCog.new, self.interaction, 'card-sample-game', None,
            UndoPolicy.SAFE, name='Friday table')

        match = Match.objects.get()
        self.assertEqual(match.name, 'Friday table')
        self.assertEqual(match.seats.get(position=0).display_name, 'Wendy')

    def test_an_unknown_game_is_refused(self):
        run(MatchCog.new, self.interaction, 'chess', None, UndoPolicy.SAFE)

        self.assertFalse(Match.objects.exists())
        self.assertIn('not installed',
                      self.interaction.followup.sent[0]['content'])

    def test_a_table_too_large_is_refused(self):
        run(MatchCog.new, self.interaction, 'card-sample-game', 9, UndoPolicy.SAFE)

        self.assertFalse(Match.objects.exists())
        self.assertIn('seats',
                      self.interaction.followup.sent[0]['content'])


class AutocompleteTests(NoDiscordMixin, TransactionTestCase):
    def test_the_installed_games_are_offered(self):
        choices = asyncio.run(game_autocomplete(mock.Mock(), 'card'))

        self.assertEqual([choice.value for choice in choices], ['card-sample-game'])

    def test_a_match_is_offered_by_its_label(self):
        match, players = bot_match()
        interaction = interaction_for(players[0], match)

        choices = asyncio.run(match_autocomplete(interaction, ''))

        self.assertEqual([choice.value for choice in choices],
                         [str(match.pk)])
        self.assertIn('Card Sample Game', choices[0].name)


class SeatingCommandTests(NoDiscordMixin, TransactionTestCase):
    def test_a_guest_takes_the_free_seat(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match)

        run(MatchCog.join, interaction, None)

        self.assertEqual(match.seats.get(position=1).player, guest)
        self.assertIn('Seat 2', interaction.followup.sent[0]['content'])

    def test_a_joined_player_keeps_their_server_name(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match, display_name='Guest name')

        run(MatchCog.join, interaction, None)

        seat = match.seats.get(position=1)
        self.assertEqual(seat.display_name, 'Guest name')

    def test_a_match_can_be_named_by_its_label(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match)

        run(MatchCog.join, interaction, match_label(match))

        self.assertEqual(match.seats.get(position=1).player, guest)

    def test_a_started_match_refuses_a_new_seat(self):
        match, _players = bot_match()
        outsider = discord_player(44, 'user44')
        interaction = interaction_for(outsider, match)

        run(MatchCog.join, interaction, None)

        self.assertIn('not open',
                      interaction.followup.sent[0]['content'])

    def test_a_seat_can_be_left_before_the_start(self):
        match, _host, guest = setup_match()
        matches.join_match(match.pk, guest)
        interaction = interaction_for(guest, match)

        run(MatchCog.leave, interaction, None)

        self.assertFalse(match.seats.filter(player=guest).exists())
        self.assertIn('free', interaction.followup.sent[0]['content'])

    def test_every_seat_must_be_taken(self):
        match, host, _guest = setup_match()
        interaction = interaction_for(host, match)

        run(MatchCog.start, interaction, None)

        self.assertIn('Every seat',
                      interaction.followup.sent[0]['content'])

    def test_a_full_table_starts(self):
        match, host, guest = setup_match()
        matches.join_match(match.pk, guest)
        interaction = interaction_for(host, match)

        run(MatchCog.start, interaction, None)

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.ACTIVE)
        self.assertIn('started', interaction.followup.sent[0]['content'])


@override_settings(WEB_BASE_URL='https://example.test')
class PlayCommandTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = bot_match()

    def test_act_opens_the_panel(self):
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.act, interaction, None)

        [message] = interaction.response.messages
        self.assertIsNotNone(message['view'])

    def test_hand_shows_only_the_callers_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.hand, interaction, None)

        description = interaction.response.messages[0]['embed'].description
        self.assertIn('ZEBRA', description)
        self.assertNotIn('UNICORN', description)

    def test_private_shows_the_same_information_as_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.private, interaction, None)

        message = interaction.response.messages[0]
        self.assertIn('ZEBRA', message['embed'].description)

    def test_status_names_the_seats(self):
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.status, interaction, None)

        embed = interaction.response.messages[0]['embed']
        self.assertIn('Seats', [field.name for field in embed.fields])

    def test_board_queues_a_refresh(self):
        before = self.match.outbox.filter(kind='board_update').count()
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.board, interaction, None)

        self.assertEqual(self.match.outbox.filter(
            kind='board_update').count(), before + 1)
        self.assertIn('Refreshing',
                      interaction.followup.sent[0]['content'])

    def test_undo_explains_a_reveal(self):
        player = self.match.active_seat.player
        play_first(self.match, player)
        interaction = interaction_for(player, self.match)

        run(MatchCog.undo, interaction, None)

        self.assertIn('only a host',
                      interaction.response.messages[0]['content'])

    def test_no_match_here_is_refused(self):
        interaction = interaction_for(self.players[0], self.match,
                                      channel_id=999)

        run(MatchCog.status, interaction, None)

        self.assertIn('No match is open',
                      interaction.response.messages[0]['content'])



class HostCommandTests(NoDiscordMixin, TransactionTestCase):
    def test_a_host_closes_the_match(self):
        match, host, _guest = setup_match()
        interaction = interaction_for(host, match)

        run(MatchCog.close, interaction, None)

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)
        self.assertIn('closed', interaction.followup.sent[0]['content'])

    def test_a_guest_cannot_close(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match)

        run(MatchCog.close, interaction, None)

        self.assertIn('Only the host',
                      interaction.followup.sent[0]['content'])

    def test_a_discord_manager_starts_someone_elses_table(self):
        match, _host, guest = setup_match()
        matches.join_match(match.pk, guest)
        interaction = interaction_for(guest, match, manage_guild=True)

        run(MatchCog.start, interaction, None)

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.ACTIVE)

    def test_a_host_upgrades_a_setup_match(self):
        match, host, _guest = setup_match()
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        interaction = interaction_for(host, match)

        run(MatchCog.upgrade, interaction, None)

        match.refresh_from_db()
        self.assertEqual(match.rules_version, CardSampleGame.version)
        self.assertIn('installed rules',
                      interaction.followup.sent[0]['content'])

    def test_a_guest_cannot_upgrade(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match)

        run(MatchCog.upgrade, interaction, None)

        self.assertIn('Only the host',
                      interaction.followup.sent[0]['content'])


class ForcedUndoTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = bot_match()

    def test_a_host_forces_an_undo_with_a_reason(self):
        play_first(self.match, self.players[0])
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.undo, interaction, None, True, 'oops')

        self.match.refresh_from_db()
        self.assertEqual(self.match.actions.get(seq=2).result,
                         {'forced': True, 'reason': 'oops'})
        self.assertIn('Undone',
                      interaction.response.messages[0]['content'])

    def test_a_forced_undo_needs_a_reason(self):
        play_first(self.match, self.players[0])
        interaction = interaction_for(self.players[0], self.match)

        run(MatchCog.undo, interaction, None, True, '')

        self.assertIn('reason',
                      interaction.response.messages[0]['content'])
        self.assertFalse(self.match.actions.filter(type='undo').exists())

    def test_a_guest_cannot_force_an_undo(self):
        play_first(self.match, self.players[0])
        interaction = interaction_for(self.players[1], self.match)

        run(MatchCog.undo, interaction, None, True, 'oops')

        self.assertIn('Only the host',
                      interaction.response.messages[0]['content'])


class ManagerCommandTests(NoDiscordMixin, TransactionTestCase):
    def test_any_match_command_seeds_a_discord_manager(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match, manage_guild=True)

        run(MatchCog.join, interaction, None)

        self.assertTrue(permissions.is_guild_manager(match.guild, guest))

    def test_a_discord_manager_adds_a_manager(self):
        match, host, guest = setup_match()
        interaction = interaction_for(host, match, manage_guild=True)
        member = FakeUser(guest.discord_user_id or 0,
                          guest.discord_name or guest.username)

        run(MatchCog.manager_add, interaction, member)

        self.assertTrue(permissions.is_guild_manager(match.guild, guest))
        self.assertIn('may now manage',
                      interaction.followup.sent[0]['content'])

    def test_a_plain_player_cannot_add_a_manager(self):
        match, host, guest = setup_match()
        interaction = interaction_for(host, match)
        member = FakeUser(guest.discord_user_id or 0,
                          guest.discord_name or guest.username)

        run(MatchCog.manager_add, interaction, member)

        self.assertIn('Only a manager',
                      interaction.followup.sent[0]['content'])
        self.assertFalse(permissions.is_guild_manager(match.guild, guest))

    def test_removing_a_manager_reports_it(self):
        match, host, guest = setup_match()
        permissions.grant_manager(match.guild, guest)
        interaction = interaction_for(host, match, manage_guild=True)
        member = FakeUser(guest.discord_user_id or 0,
                          guest.discord_name or guest.username)

        run(MatchCog.manager_remove, interaction, member)

        self.assertFalse(permissions.is_guild_manager(match.guild, guest))
        self.assertIn('may no longer',
                      interaction.followup.sent[0]['content'])

    def test_a_discord_admin_keeps_the_permission(self):
        match, host, guest = setup_match()
        permissions.grant_manager(match.guild, guest)
        interaction = interaction_for(host, match, manage_guild=True)
        member = FakeUser(guest.discord_user_id or 0,
                          guest.discord_name or guest.username,
                          manage_guild=True)

        run(MatchCog.manager_remove, interaction, member)

        self.assertTrue(permissions.is_guild_manager(match.guild, guest))
        self.assertIn('in Discord',
                      interaction.followup.sent[0]['content'])

