"""Tests for the models, checked without touching the database."""

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.test import SimpleTestCase

from core.models import Guild, Player
from games.models import (Action, ActionSnapshot, Match, MatchStatus,
                          OutboxMessage, OutboxStatus, PendingChoice, Seat,
                          UndoPolicy)


class CoreModelTests(SimpleTestCase):
    def test_the_player_is_the_user_model(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'core.Player')
        self.assertEqual(Player._meta.label, 'core.Player')

    def test_a_discord_account_identifies_a_player(self):
        self.assertTrue(Player._meta.get_field('discord_user_id').unique)
        self.assertTrue(Player._meta.get_field('discord_name').unique)
        self.assertTrue(Player._meta.get_field('email').unique)
        with self.assertRaises(FieldDoesNotExist):
            Player._meta.get_field('first_name')

    def test_a_guild_is_identified_by_its_discord_id(self):
        self.assertTrue(Guild._meta.get_field('discord_id').unique)


class MatchModelTests(SimpleTestCase):
    def test_public_and_hidden_state_are_separate(self):
        self.assertIsInstance(Match._meta.get_field('state'), models.JSONField)
        self.assertIsInstance(Match._meta.get_field('hidden_state'),
                              models.JSONField)
        self.assertEqual(Match._meta.get_field('version').default, 0)

    def test_the_active_seat_points_at_a_seat(self):
        self.assertIs(Match._meta.get_field('active_seat').remote_field.model,
                      Seat)

    def test_a_match_starts_in_setup(self):
        self.assertEqual(Match._meta.get_field('status').default,
                         MatchStatus.SETUP)

    def test_a_seat_is_unique_per_position_and_per_player(self):
        names = {constraint.name for constraint in Seat._meta.constraints}
        self.assertEqual(names,
                         {'unique_seat_position', 'unique_seat_player'})

    def test_an_action_sequence_is_unique_per_match(self):
        names = {constraint.name for constraint in Action._meta.constraints}
        self.assertIn('unique_action_seq', names)

    def test_an_outbox_message_starts_pending(self):
        self.assertEqual(OutboxMessage._meta.get_field('status').default,
                         OutboxStatus.PENDING)
        self.assertEqual(OutboxMessage._meta.get_field('attempts').default, 0)

    def test_a_pending_choice_records_its_answer(self):
        self.assertIsInstance(PendingChoice._meta.get_field('response'),
                              models.JSONField)
        self.assertIsInstance(PendingChoice._meta.get_field('options'),
                              models.JSONField)


class UndoModelTests(SimpleTestCase):
    def test_a_match_tracks_its_position_and_policy(self):
        self.assertEqual(Match._meta.get_field('position').default, 0)
        self.assertEqual(Match._meta.get_field('undo_policy').default,
                         UndoPolicy.SAFE)

    def test_an_action_records_whether_it_can_be_reversed(self):
        self.assertEqual(Action._meta.get_field('random').default, False)
        self.assertEqual(Action._meta.get_field('revealed').default, False)

    def test_every_action_keeps_the_state_it_replaced(self):
        field = ActionSnapshot._meta.get_field('action')
        self.assertIsInstance(field, models.OneToOneField)
        self.assertEqual(field.remote_field.model, Action)
