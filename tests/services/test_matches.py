"""Tests for creating, seating, starting and closing a match."""

from django.test import TestCase

from games.models import MatchStatus, OutboxMessage, UndoPolicy
from core import permissions
from games.services import log, matches, undo
from games.services.errors import (AlreadySeated, MatchClosed, MatchFull,
                                   NotHost, SeatsOpen, UnknownGame)
from tests.factories import (make_guild, make_player, play_first,
                             started_match)


class CreateMatchTests(TestCase):
    def setUp(self):
        self.guild = make_guild()
        self.host = make_player('host')

    def test_a_new_match_is_dealt_and_seated(self):
        match = matches.create_match(guild=self.guild, channel_id=2,
                                     slug='card-sample-game', player=self.host, seed=9)
        self.assertEqual(match.status, MatchStatus.SETUP)
        self.assertEqual(match.version, 0)
        self.assertEqual(match.position, 0)
        self.assertEqual(match.undo_policy, UndoPolicy.SAFE)
        self.assertEqual(match.seats.count(), 2)
        self.assertEqual(match.seats.get(position=0).player, self.host)
        self.assertEqual(match.host, self.host)
        self.assertEqual(len(match.hidden_state['deck']), 18)
        hand = match.seats.get(position=0).private_state['hand']
        self.assertEqual(len(hand), 3)

    def test_a_match_can_be_named_and_its_host_named(self):
        match = matches.create_match(
            guild=self.guild, channel_id=2, slug='card-sample-game',
            player=self.host, name='Friday table', seat_name='Wendy',
            seed=9)

        self.assertEqual(match.name, 'Friday table')
        self.assertEqual(match.seats.get(position=0).display_name, 'Wendy')
        self.assertEqual(matches.match_title(match, 'Card Sample Game'),
                         f'Card Sample Game: Friday table (#{match.pk})')

    def test_a_match_name_is_bounded(self):
        with self.assertRaises(ValueError):
            matches.create_match(
                guild=self.guild, channel_id=2, slug='card-sample-game',
                player=self.host, name='x' * 101)

    def test_an_unknown_game_is_refused(self):
        with self.assertRaises(UnknownGame):
            matches.create_match(guild=self.guild, channel_id=2, slug='nope',
                                 player=self.host)

    def test_the_table_size_is_bounded(self):
        with self.assertRaises(ValueError):
            matches.create_match(guild=self.guild, channel_id=2,
                                 slug='card-sample-game', player=self.host, seats=9)


class SeatingTests(TestCase):
    def setUp(self):
        self.guild = make_guild()
        self.host = make_player('host')
        self.guest = make_player('guest')
        self.match = matches.create_match(guild=self.guild, channel_id=2,
                                          slug='card-sample-game', player=self.host,
                                          seed=4)

    def test_a_guest_takes_the_first_free_seat(self):
        seat = matches.join_match(self.match.pk, self.guest)
        self.assertEqual(seat.position, 1)
        with self.assertRaises(AlreadySeated):
            matches.join_match(self.match.pk, self.guest)

    def test_a_full_match_refuses_more_players(self):
        matches.join_match(self.match.pk, self.guest)
        with self.assertRaises(MatchFull):
            matches.join_match(self.match.pk, make_player('third'))

    def test_a_seat_can_be_left_before_the_start(self):
        matches.join_match(self.match.pk, self.guest)
        matches.leave_match(self.match.pk, self.guest)
        self.assertFalse(self.match.seats.filter(player=self.guest).exists())

    def test_join_and_leave_keep_the_seat_name(self):
        seat = matches.join_match(self.match.pk, self.guest, seat_name='Guest')
        self.assertEqual(seat.display_name, 'Guest')

        seat = matches.leave_match(self.match.pk, self.guest)
        self.assertEqual(seat.display_name, '')

    def test_a_match_starts_with_every_seat_taken(self):
        with self.assertRaises(SeatsOpen):
            matches.start_match(self.match.pk, self.host)
        matches.join_match(self.match.pk, self.guest)
        match = matches.start_match(self.match.pk, self.host)
        self.assertEqual(match.status, MatchStatus.ACTIVE)
        self.assertEqual(match.active_seat.position, 0)

    def test_a_seated_guest_cannot_start(self):
        matches.join_match(self.match.pk, self.guest)

        with self.assertRaises(NotHost):
            matches.start_match(self.match.pk, self.guest)

    def test_a_server_manager_can_start(self):
        matches.join_match(self.match.pk, self.guest)
        permissions.grant_manager(self.guild, self.guest)

        match = matches.start_match(self.match.pk, self.guest)

        self.assertEqual(match.status, MatchStatus.ACTIVE)

    def test_a_guest_cannot_close(self):
        with self.assertRaises(NotHost):
            matches.close_match(self.match.pk, self.guest)

    def test_a_server_manager_can_close(self):
        permissions.grant_manager(self.guild, self.guest)

        match = matches.close_match(self.match.pk, self.guest)

        self.assertEqual(match.status, MatchStatus.FINISHED)

    def test_a_started_match_cannot_be_joined(self):
        matches.join_match(self.match.pk, self.guest)
        matches.start_match(self.match.pk, self.host)
        with self.assertRaises(MatchClosed):
            matches.join_match(self.match.pk, make_player('third'))

    def test_closing_a_match_queues_a_board_update(self):
        match = matches.close_match(self.match.pk, self.host)
        self.assertEqual(match.status, MatchStatus.FINISHED)
        self.assertIsNotNone(match.finished_at)
        self.assertTrue(OutboxMessage.objects.filter(
            match=match, kind='board_update').exists())
        self.assertTrue(OutboxMessage.objects.filter(
            match=match, kind='match_over').exists())

    def test_a_close_is_recorded_as_an_undoable_action(self):
        matches.join_match(self.match.pk, self.guest)
        matches.start_match(self.match.pk, self.host)
        match = matches.close_match(self.match.pk, self.host)
        record = match.actions.get(seq=match.version)
        self.assertEqual(record.type, 'close_match')
        match = undo.undo_last_action(match.pk, self.host)
        self.assertEqual(match.status, MatchStatus.ACTIVE)
        self.assertIsNone(match.finished_at)
        self.assertIsNotNone(match.active_seat_id)



class BoardUpdateTests(TestCase):
    def setUp(self):
        self.guild = make_guild()
        self.host = make_player('host')
        self.guest = make_player('guest')
        self.match = matches.create_match(guild=self.guild, channel_id=2,
                                          slug='card-sample-game', player=self.host,
                                          seed=4)

    def test_opening_a_match_queues_its_board(self):
        self.assertTrue(OutboxMessage.objects.filter(
            match=self.match, kind='board_update').exists())

    def test_seating_and_starting_queue_updates(self):
        def updates():
            return OutboxMessage.objects.filter(
                match=self.match, kind='board_update').count()

        before = updates()
        matches.join_match(self.match.pk, self.guest)
        joined = updates()
        self.assertGreater(joined, before)
        matches.start_match(self.match.pk, self.host)
        self.assertGreater(updates(), joined)

    def test_leaving_queues_an_update(self):
        matches.join_match(self.match.pk, self.guest)
        before = OutboxMessage.objects.filter(
            match=self.match, kind='board_update').count()

        matches.leave_match(self.match.pk, self.guest)

        self.assertGreater(OutboxMessage.objects.filter(
            match=self.match, kind='board_update').count(), before)



class DeletedPlayerTests(TestCase):
    def test_the_seat_and_the_log_survive_the_player(self):
        match, players = started_match()
        match = play_first(match, players[0])
        players[0].delete()
        match.refresh_from_db()

        self.assertTrue(match.seats.filter(position=0).exists())
        self.assertIsNone(match.host)
        self.assertIsNone(match.actions.get(seq=1).actor)
        self.assertEqual(log.entries(match)[0]['actor'], '')

