"""Tests for actions taken by a pending, non-active seat."""

from django.test import TestCase

from games.models import PendingChoice
from games.services import actions, undo
from games.services.projections import render_model
from tests.factories import started_match
from tests.games.pending_game import ensure_registered


class OutOfTurnServiceTests(TestCase):
    def setUp(self):
        ensure_registered()
        self.match, self.players = started_match(
            players=2, slug='pending-reaction-game')

    def open_reaction(self):
        option = render_model(self.match, self.players[0]).actions[0]
        self.match = actions.apply_action(
            self.match.pk, self.players[0], option.id)
        return PendingChoice.objects.get(
            match=self.match, resolved_at__isnull=True)

    def test_the_pending_seat_is_not_the_active_seat(self):
        choice = self.open_reaction()

        self.assertEqual(self.match.active_seat.position, 0)
        self.assertEqual(choice.seat.position, 1)

    def test_a_pending_non_active_seat_can_apply_an_action(self):
        self.open_reaction()

        model = render_model(self.match, self.players[1])
        self.assertEqual([option.id for option in model.actions], ['react'])
        self.assertEqual(model.pending.kind, 'react')

        self.match = actions.apply_action(
            self.match.pk, self.players[1], 'react',
            {'answer': 'accept'})

        self.assertEqual(self.match.active_seat.position, 0)
        self.assertFalse(self.match.pending_choices.filter(
            resolved_at__isnull=True).exists())

    def test_undo_restores_the_out_of_turn_choice(self):
        self.open_reaction()
        self.match = actions.apply_action(
            self.match.pk, self.players[1], 'react', {'answer': 'decline'})

        self.match = undo.undo_last_action(
            self.match.pk, self.players[0], force=True)

        self.assertEqual(self.match.active_seat.position, 0)
        self.assertTrue(self.match.pending_choices.filter(
            resolved_at__isnull=True, seat__position=1).exists())
